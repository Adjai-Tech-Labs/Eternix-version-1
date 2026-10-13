"""Workspace indexing and retrieval tools.

Indexes selected workspace files into the Qdrant-backed memory store so the
agent can answer questions about a project without re-reading every file.
Chunking is line-based with a configurable window; metadata preserves the
source path so results can be attributed.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from eternix.core.config import settings
from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.memory import MemoryManager
from eternix.tools.registry import tool_registry

_IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", ".tox",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist", "venv",
    "env", ".cache", ".idea", ".vscode", "huggingface-cache",
}
_IGNORED_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".zip",
    ".tar", ".gz", ".tgz", ".pdf", ".docx", ".xlsx", ".pptx", ".pyc",
    ".so", ".dylib", ".dll", ".bin", ".gguf", ".onnx",
}


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in _IGNORED_EXTS:
                continue
            p = Path(dirpath) / name
            try:
                if p.stat().st_size > settings.max_file_size_bytes:
                    continue
            except OSError:
                continue
            yield p


def _chunk(text: str, max_lines: int = 60):
    lines = text.splitlines()
    for i in range(0, len(lines), max_lines):
        yield "\n".join(lines[i : i + max_lines])


async def index_workspace_handler(
    input_data: dict[str, Any], task: Task, task_store: TaskStore
) -> ToolResult:
    root = input_data.get("path", str(settings.default_workspace))
    max_files = input_data.get("max_files", settings.max_workspace_files)
    root_path = Path(root).resolve()
    if not root_path.exists():
        return ToolResult(
            tool_id="workspace.index",
            task_id=task.id,
            success=False,
            error=f"Workspace path does not exist: {root}",
        )

    manager = MemoryManager(task_store)
    files_indexed = 0
    chunks_stored = 0
    errors: list[str] = []
    for f in _iter_files(root_path):
        if files_indexed >= max_files:
            break
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append(f"{f}: {e}")
            continue
        rel = str(f.relative_to(root_path))
        for chunk in _chunk(text):
            payload = {
                "path": rel,
                "chunk_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:16],
            }
            await manager.add_memory(chunk, payload)
            chunks_stored += 1
        files_indexed += 1

    return ToolResult(
        tool_id="workspace.index",
        task_id=task.id,
        success=True,
        output={
            "workspace": str(root_path),
            "files_indexed": files_indexed,
            "chunks_stored": chunks_stored,
            "errors": errors[:20],
        },
    )


async def workspace_search_handler(
    input_data: dict[str, Any], task: Task, task_store: TaskStore
) -> ToolResult:
    query = input_data.get("query", "")
    if not query:
        return ToolResult(
            tool_id="workspace.search",
            task_id=task.id,
            success=False,
            error="No query provided",
        )
    manager = MemoryManager(task_store)
    results = await manager.search_memory(query, limit=input_data.get("limit", 10))
    return ToolResult(
        tool_id="workspace.search",
        task_id=task.id,
        success=True,
        output={"query": query, "results": results},
    )


def register_workspace_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="workspace.index",
            name="Index Workspace",
            description="Index workspace files into semantic memory for later retrieval",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": str(settings.default_workspace)},
                    "max_files": {"type": "integer", "default": settings.max_workspace_files},
                },
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=300,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["workspace", "index", "memory"],
        ),
        index_workspace_handler,
    )
    tool_registry.register(
        ToolDefinition(
            id="workspace.search",
            name="Search Workspace",
            description="Search indexed workspace content semantically",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["workspace", "search", "memory"],
        ),
        workspace_search_handler,
    )