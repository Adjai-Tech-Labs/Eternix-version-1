import uuid
from datetime import UTC, datetime
from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    QdrantClient = None
    Distance = VectorParams = PointStruct = Filter = FieldCondition = MatchValue = None

from eternix.core.config import settings
from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.registry import tool_registry


class MemoryManager:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store
        self.client = None
        self.collection = settings.memory_collection
        self.embedding_dim = settings.embedding_dim
        self._fallback_memories: dict[str, dict[str, Any]] = {}
        
        if QDRANT_AVAILABLE:
            try:
                self.client = QdrantClient(path=str(settings.qdrant_path))
                self._ensure_collection()
            except Exception:
                self.client = None

    def _ensure_collection(self) -> None:
        if not self.client:
            return
        try:
            collections = self.client.get_collections().collections
            if not any(c.name == self.collection for c in collections):
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
                )
        except Exception:
            self.client = None

    def _get_embedding(self, text: str) -> list[float]:
        try:
            from fastembed import TextEmbedding
            embedding_model = TextEmbedding(model_name="Qwen/Qwen3-Embedding-0.6B")
            embeddings = list(embedding_model.embed([text]))
            if embeddings:
                return embeddings[0].tolist()
        except Exception:
            pass
        return [0.0] * self.embedding_dim

    async def add_memory(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        point_id = str(uuid.uuid4())
        vector = self._get_embedding(content)

        payload = {
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
            **(metadata or {}),
        }

        if self.client:
            try:
                self.client.upsert(
                    collection_name=self.collection,
                    points=[PointStruct(id=point_id, vector=vector, payload=payload)],
                )
                return point_id
            except Exception:
                pass

        # Fallback to in-memory storage
        self._fallback_memories[point_id] = payload
        return point_id

    async def search_memory(self, query: str, limit: int = 10, filter_metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        vector = self._get_embedding(query)

        if self.client:
            try:
                query_filter = None
                if filter_metadata:
                    conditions = [
                        FieldCondition(key=k, match=MatchValue(value=v))
                        for k, v in filter_metadata.items()
                    ]
                    query_filter = Filter(must=conditions)

                results = self.client.search(
                    collection_name=self.collection,
                    query_vector=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )

                return [
                    {
                        "id": str(r.id),
                        "score": r.score,
                        "content": r.payload.get("content", ""),
                        "metadata": {k: v for k, v in r.payload.items() if k != "content"},
                    }
                    for r in results
                ]
            except Exception:
                pass

        # Fallback: simple text search in fallback memories
        results = []
        query_lower = query.lower()
        for pid, payload in self._fallback_memories.items():
            content = payload.get("content", "")
            if query_lower in content.lower():
                results.append({
                    "id": pid,
                    "score": 1.0,
                    "content": content,
                    "metadata": {k: v for k, v in payload.items() if k != "content"},
                })
                if len(results) >= limit:
                    break
        return results

    async def delete_memory(self, point_id: str) -> bool:
        if self.client:
            try:
                self.client.delete(collection_name=self.collection, points_selector=[point_id])
                return True
            except Exception:
                pass

        if point_id in self._fallback_memories:
            del self._fallback_memories[point_id]
            return True
        return False

    async def get_memory(self, point_id: str) -> dict[str, Any] | None:
        if self.client:
            try:
                results = self.client.retrieve(collection_name=self.collection, ids=[point_id], with_payload=True, with_vectors=False)
                if results:
                    r = results[0]
                    return {
                        "id": str(r.id),
                        "content": r.payload.get("content", ""),
                        "metadata": {k: v for k, v in r.payload.items() if k != "content"},
                    }
            except Exception:
                pass

        if point_id in self._fallback_memories:
            payload = self._fallback_memories[point_id]
            return {
                "id": point_id,
                "content": payload.get("content", ""),
                "metadata": {k: v for k, v in payload.items() if k != "content"},
            }
        return None


_memory_manager: MemoryManager | None = None


def get_memory_manager(task_store: TaskStore) -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(task_store)
    return _memory_manager


async def memory_add_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    content = input_data.get("content", "")
    metadata = input_data.get("metadata", {})

    if not content:
        return ToolResult(
            tool_id="memory.add",
            task_id=task.id,
            success=False,
            error="No content provided",
        )

    try:
        manager = get_memory_manager(task_store)
        point_id = await manager.add_memory(content, metadata)
        return ToolResult(
            tool_id="memory.add",
            task_id=task.id,
            success=True,
            output={"id": point_id, "content": content[:100] + "..." if len(content) > 100 else content},
        )
    except Exception as e:
        return ToolResult(
            tool_id="memory.add",
            task_id=task.id,
            success=False,
            error=f"Failed to add memory: {e}",
        )


async def memory_search_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    query = input_data.get("query", "")
    limit = input_data.get("limit", 10)
    filter_metadata = input_data.get("filter", {})

    if not query:
        return ToolResult(
            tool_id="memory.search",
            task_id=task.id,
            success=False,
            error="No query provided",
        )

    try:
        manager = get_memory_manager(task_store)
        results = await manager.search_memory(query, limit, filter_metadata)
        return ToolResult(
            tool_id="memory.search",
            task_id=task.id,
            success=True,
            output={"query": query, "results": results},
        )
    except Exception as e:
        return ToolResult(
            tool_id="memory.search",
            task_id=task.id,
            success=False,
            error=f"Search failed: {e}",
        )


async def memory_delete_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    point_id = input_data.get("id", "")

    if not point_id:
        return ToolResult(
            tool_id="memory.delete",
            task_id=task.id,
            success=False,
            error="No memory ID provided",
        )

    try:
        manager = get_memory_manager(task_store)
        success = await manager.delete_memory(point_id)
        return ToolResult(
            tool_id="memory.delete",
            task_id=task.id,
            success=success,
            output={"id": point_id, "deleted": success},
        )
    except Exception as e:
        return ToolResult(
            tool_id="memory.delete",
            task_id=task.id,
            success=False,
            error=f"Delete failed: {e}",
        )


async def memory_get_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    point_id = input_data.get("id", "")

    if not point_id:
        return ToolResult(
            tool_id="memory.get",
            task_id=task.id,
            success=False,
            error="No memory ID provided",
        )

    try:
        manager = get_memory_manager(task_store)
        result = await manager.get_memory(point_id)
        if result:
            return ToolResult(
                tool_id="memory.get",
                task_id=task.id,
                success=True,
                output=result,
            )
        else:
            return ToolResult(
                tool_id="memory.get",
                task_id=task.id,
                success=False,
                error="Memory not found",
            )
    except Exception as e:
        return ToolResult(
            tool_id="memory.get",
            task_id=task.id,
            success=False,
            error=f"Get failed: {e}",
        )


def register_memory_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="memory.add",
            name="Add Memory",
            description="Add content to long-term memory with embeddings",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["content"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["memory", "add", "embeddings"],
        ),
        memory_add_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="memory.search",
            name="Search Memory",
            description="Search memory using semantic similarity",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "filter": {"type": "object"},
                },
                "required": ["query"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["memory", "search", "retrieval"],
        ),
        memory_search_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="memory.delete",
            name="Delete Memory",
            description="Delete a memory entry",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                },
                "required": ["id"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["memory", "delete"],
        ),
        memory_delete_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="memory.get",
            name="Get Memory",
            description="Retrieve a specific memory entry",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                },
                "required": ["id"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["memory", "get"],
        ),
        memory_get_handler,
    )