from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ddgs import DDGS
from trafilatura import extract, fetch_url

from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.registry import tool_registry


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str
    timestamp: datetime


@dataclass
class ExtractedContent:
    url: str
    title: str
    content: str
    author: str | None
    publish_date: str | None
    images: list[str]
    metadata: dict[str, Any]


class WebResearchCapability:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store
        self.ddgs = DDGS()
        self._search_cache: dict[str, list[SearchResult]] = {}

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        cache_key = f"{query}:{max_results}"
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]

        try:
            results = []
            for r in self.ddgs.text(query, max_results=max_results, region="us-en"):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                    source=r.get("source", "duckduckgo"),
                    timestamp=datetime.now(UTC),
                ))

            self._search_cache[cache_key] = results
            return results
        except Exception:
            return []

    async def extract_content(self, url: str) -> ExtractedContent | None:
        try:
            downloaded = fetch_url(url)
            if not downloaded:
                return None

            content = extract(
                downloaded,
                include_images=True,
                include_links=True,
                include_tables=True,
                no_fallback=False,
            )

            if not content:
                return None

            metadata = extract(downloaded, output_format="json", include_metadata=True)
            import json
            meta = json.loads(metadata) if metadata else {}

            return ExtractedContent(
                url=url,
                title=meta.get("title", ""),
                content=content,
                author=meta.get("author"),
                publish_date=meta.get("date"),
                images=meta.get("images", []),
                metadata=meta,
            )
        except Exception:
            return None

    async def research(self, query: str, max_sources: int = 5) -> dict[str, Any]:
        search_results = await self.search(query, max_results=max_sources * 2)

        extracted = []
        for result in search_results[:max_sources]:
            content = await self.extract_content(result.url)
            if content and len(content.content) > 200:
                extracted.append({
                    "source": result,
                    "content": content,
                    "citation_id": str(uuid4())[:8],
                })

        synthesis = await self._synthesize(query, extracted)

        return {
            "query": query,
            "sources": extracted,
            "synthesis": synthesis,
            "citations": [
                {
                    "id": e["citation_id"],
                    "title": e["source"].title,
                    "url": e["source"].url,
                    "snippet": e["source"].snippet,
                    "timestamp": e["source"].timestamp.isoformat(),
                }
                for e in extracted
            ],
        }

    async def _synthesize(self, query: str, sources: list[dict]) -> str:
        if not sources:
            return "No relevant sources found."

        parts = [f"Research results for: {query}\n"]
        for i, src in enumerate(sources, 1):
            parts.append(f"[{src['citation_id']}] {src['source'].title}")
            parts.append(f"    URL: {src['source'].url}")
            content = src['content'].content[:500]
            parts.append(f"    {content}...")
            parts.append("")

        return "\n".join(parts)

    async def search_images(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        try:
            results = []
            for r in self.ddgs.images(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("image", ""),
                    "thumbnail": r.get("thumbnail", ""),
                    "source": r.get("source", ""),
                    "width": r.get("width"),
                    "height": r.get("height"),
                })
            return results
        except Exception:
            return []


async def web_search_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    query = input_data.get("query", "")
    max_results = input_data.get("max_results", 10)

    if not query:
        return ToolResult(
            tool_id="web.search",
            task_id=task.id,
            success=False,
            error="No query specified",
        )

    capability = WebResearchCapability(task_store)
    results = await capability.search(query, max_results)

    return ToolResult(
        tool_id="web.search",
        task_id=task.id,
        success=True,
        output={
            "query": query,
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "source": r.source,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in results
            ],
        },
    )


async def web_extract_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    url = input_data.get("url", "")

    if not url:
        return ToolResult(
            tool_id="web.extract",
            task_id=task.id,
            success=False,
            error="No URL specified",
        )

    capability = WebResearchCapability(task_store)
    content = await capability.extract_content(url)

    if not content:
        return ToolResult(
            tool_id="web.extract",
            task_id=task.id,
            success=False,
            error="Failed to extract content",
        )

    return ToolResult(
        tool_id="web.extract",
        task_id=task.id,
        success=True,
        output={
            "url": content.url,
            "title": content.title,
            "content": content.content,
            "author": content.author,
            "publish_date": content.publish_date,
            "images": content.images,
            "metadata": content.metadata,
        },
    )


async def web_research_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    query = input_data.get("query", "")
    max_sources = input_data.get("max_sources", 5)

    if not query:
        return ToolResult(
            tool_id="web.research",
            task_id=task.id,
            success=False,
            error="No query specified",
        )

    capability = WebResearchCapability(task_store)
    result = await capability.research(query, max_sources)

    return ToolResult(
        tool_id="web.research",
        task_id=task.id,
        success=True,
        output=result,
    )


async def web_search_images_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    query = input_data.get("query", "")
    max_results = input_data.get("max_results", 10)

    if not query:
        return ToolResult(
            tool_id="web.search_images",
            task_id=task.id,
            success=False,
            error="No query specified",
        )

    capability = WebResearchCapability(task_store)
    results = await capability.search_images(query, max_results)

    return ToolResult(
        tool_id="web.search_images",
        task_id=task.id,
        success=True,
        output={"query": query, "images": results},
    )


def register_web_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="web.search",
            name="Web Search",
            description="Search the web for information",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.EXTERNAL_NETWORK,
            tags=["web", "search", "research"],
        ),
        web_search_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="web.extract",
            name="Extract Web Content",
            description="Extract main content from a web page",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.EXTERNAL_NETWORK,
            tags=["web", "extract", "research"],
        ),
        web_extract_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="web.research",
            name="Deep Web Research",
            description="Conduct multi-source research with citations",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_sources": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=120,
            side_effect=ToolSideEffect.EXTERNAL_NETWORK,
            tags=["web", "research", "citations"],
        ),
        web_research_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="web.search_images",
            name="Search Images",
            description="Search for images on the web",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.EXTERNAL_NETWORK,
            tags=["web", "images", "search"],
        ),
        web_search_images_handler,
    )