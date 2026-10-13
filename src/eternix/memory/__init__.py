"""ETERNIX long-term memory module.

Provides semantic memory storage and retrieval using vector embeddings.
"""

from contextlib import asynccontextmanager

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from eternix.core.config import settings


class MemoryManager:
    """Manages long-term semantic memory using Qdrant vector store."""

    def __init__(self, collection: str = settings.memory_collection):
        self.collection = collection
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(path=str(settings.qdrant_path))
        return self._client

    def _ensure_collection(self) -> None:
        try:
            self.client.get_collection(self.collection)
        except Exception:
            self.client.recreate_collection(
                collection_name=self.collection,
                vectors_config=qdrant_models.VectorParams(
                    size=settings.embedding_dim,
                    distance=qdrant_models.Distance.COSINE,
                ),
            )

    async def store(self, text: str, embedding: list[float], metadata: dict | None = None) -> str:
        self._ensure_collection()
        point_id = str(hash(text) & 0xFFFFFF)
        self.client.upsert(
            collection_name=self.collection,
            points=[
                qdrant_models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={"text": text, **(metadata or {})},
                )
            ],
        )
        return point_id

    async def search(self, embedding: list[float], limit: int = 5) -> list[dict]:
        self._ensure_collection()
        results = self.client.search(
            collection_name=self.collection,
            query_vector=embedding,
            limit=limit,
        )
        return [
            {"text": r.payload.get("text", ""), "score": r.score, "metadata": r.payload}
            for r in results
        ]

    async def delete(self, point_id: str) -> None:
        self._ensure_collection()
        self.client.delete(collection_name=self.collection, points=[point_id])

    async def clear(self) -> None:
        self._ensure_collection()
        self.client.delete_all(collection_name=self.collection)


@asynccontextmanager
async def memory_session(collection: str = settings.memory_collection):
    """Context manager for a scoped memory session."""
    mgr = MemoryManager(collection)
    try:
        yield mgr
    finally:
        if mgr._client is not None:
            mgr._client.close()
