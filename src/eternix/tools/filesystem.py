import os
import shutil
from pathlib import Path
from typing import Any

from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.registry import tool_registry


def _resolve_path(path: str, task: Task) -> Path:
    base = Path.cwd()
    if task.input_data.get("working_dir"):
        base = Path(task.input_data["working_dir"])
    return (base / path).resolve()


async def fs_list_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = _resolve_path(input_data.get("path", "."), task)
    if not path.exists():
        return ToolResult(
            tool_id="fs.list",
            task_id=task.id,
            success=False,
            error=f"Path does not exist: {path}",
        )

    if path.is_file():
        stat = path.stat()
        return ToolResult(
            tool_id="fs.list",
            task_id=task.id,
            success=True,
            output={
                "path": str(path),
                "is_file": True,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            },
        )

    entries = []
    for entry in path.iterdir():
        stat = entry.stat()
        entries.append(
            {
                "name": entry.name,
                "path": str(entry),
                "is_file": entry.is_file(),
                "is_dir": entry.is_dir(),
                "size": stat.st_size if entry.is_file() else None,
                "modified": stat.st_mtime,
            }
        )

    return ToolResult(
        tool_id="fs.list",
        task_id=task.id,
        success=True,
        output={"path": str(path), "entries": entries},
    )


async def fs_read_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = _resolve_path(input_data.get("path", ""), task)
    if not path.exists() or not path.is_file():
        return ToolResult(
            tool_id="fs.read",
            task_id=task.id,
            success=False,
            error=f"File does not exist: {path}",
        )

    encoding = input_data.get("encoding", "utf-8")
    max_bytes = input_data.get("max_bytes", 1024 * 1024)

    try:
        content = path.read_bytes()[:max_bytes]
        text = content.decode(encoding, errors="replace")
        return ToolResult(
            tool_id="fs.read",
            task_id=task.id,
            success=True,
            output={"path": str(path), "content": text, "size": len(content), "encoding": encoding},
        )
    except OSError as e:
        return ToolResult(
            tool_id="fs.read",
            task_id=task.id,
            success=False,
            error=f"Failed to read file: {e}",
        )


async def fs_write_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = _resolve_path(input_data.get("path", ""), task)
    content = input_data.get("content", "")
    encoding = input_data.get("encoding", "utf-8")
    create_dirs = input_data.get("create_dirs", True)

    try:
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return ToolResult(
            tool_id="fs.write",
            task_id=task.id,
            success=True,
            output={"path": str(path), "size": len(content.encode(encoding))},
        )
    except OSError as e:
        return ToolResult(
            tool_id="fs.write",
            task_id=task.id,
            success=False,
            error=f"Failed to write file: {e}",
        )


async def fs_mkdir_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = _resolve_path(input_data.get("path", ""), task)
    try:
        path.mkdir(parents=True, exist_ok=True)
        return ToolResult(
            tool_id="fs.mkdir",
            task_id=task.id,
            success=True,
            output={"path": str(path)},
        )
    except OSError as e:
        return ToolResult(
            tool_id="fs.mkdir",
            task_id=task.id,
            success=False,
            error=f"Failed to create directory: {e}",
        )


async def fs_copy_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    src = _resolve_path(input_data.get("src", ""), task)
    dst = _resolve_path(input_data.get("dst", ""), task)
    try:
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return ToolResult(
            tool_id="fs.copy",
            task_id=task.id,
            success=True,
            output={"src": str(src), "dst": str(dst)},
        )
    except OSError as e:
        return ToolResult(
            tool_id="fs.copy",
            task_id=task.id,
            success=False,
            error=f"Failed to copy: {e}",
        )


async def fs_move_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    src = _resolve_path(input_data.get("src", ""), task)
    dst = _resolve_path(input_data.get("dst", ""), task)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return ToolResult(
            tool_id="fs.move",
            task_id=task.id,
            success=True,
            output={"src": str(src), "dst": str(dst)},
        )
    except OSError as e:
        return ToolResult(
            tool_id="fs.move",
            task_id=task.id,
            success=False,
            error=f"Failed to move: {e}",
        )


async def fs_delete_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = _resolve_path(input_data.get("path", ""), task)
    recursive = input_data.get("recursive", False)
    try:
        if path.is_dir():
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()
        else:
            path.unlink()
        return ToolResult(
            tool_id="fs.delete",
            task_id=task.id,
            success=True,
            output={"path": str(path)},
        )
    except OSError as e:
        return ToolResult(
            tool_id="fs.delete",
            task_id=task.id,
            success=False,
            error=f"Failed to delete: {e}",
        )


async def fs_search_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = _resolve_path(input_data.get("path", "."), task)
    pattern = input_data.get("pattern", "*")
    content_pattern = input_data.get("content_pattern")
    max_results = input_data.get("max_results", 100)

    import fnmatch
    import re

    results = []
    content_regex = re.compile(content_pattern) if content_pattern else None

    for root, dirs, files in os.walk(path):
        for file in files:
            if fnmatch.fnmatch(file, pattern):
                filepath = Path(root) / file
                if content_regex:
                    try:
                        text = filepath.read_text(errors="ignore")
                        if not content_regex.search(text):
                            continue
                    except OSError:
                        continue
                results.append(
                    {
                        "path": str(filepath),
                        "name": file,
                        "size": filepath.stat().st_size,
                    }
                )
                if len(results) >= max_results:
                    break

    return ToolResult(
        tool_id="fs.search",
        task_id=task.id,
        success=True,
        output={"path": str(path), "pattern": pattern, "results": results},
    )


def register_filesystem_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="fs.list",
            name="List Files",
            description="List files and directories at a given path",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["filesystem", "read"],
        ),
        fs_list_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="fs.read",
            name="Read File",
            description="Read the contents of a file",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "encoding": {"type": "string", "default": "utf-8"},
                    "max_bytes": {"type": "integer", "default": 1048576},
                },
                "required": ["path"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["filesystem", "read"],
        ),
        fs_read_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="fs.write",
            name="Write File",
            description="Write content to a file",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "encoding": {"type": "string", "default": "utf-8"},
                    "create_dirs": {"type": "boolean", "default": True},
                },
                "required": ["path", "content"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["filesystem", "write"],
        ),
        fs_write_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="fs.mkdir",
            name="Create Directory",
            description="Create a directory",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["filesystem", "write"],
        ),
        fs_mkdir_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="fs.copy",
            name="Copy File/Directory",
            description="Copy a file or directory",
            input_schema={
                "type": "object",
                "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
                "required": ["src", "dst"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["filesystem", "write"],
        ),
        fs_copy_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="fs.move",
            name="Move File/Directory",
            description="Move or rename a file or directory",
            input_schema={
                "type": "object",
                "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
                "required": ["src", "dst"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["filesystem", "write"],
        ),
        fs_move_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="fs.delete",
            name="Delete File/Directory",
            description="Delete a file or directory",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean", "default": False},
                },
                "required": ["path"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.DESTRUCTIVE,
            tags=["filesystem", "write"],
        ),
        fs_delete_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="fs.search",
            name="Search Files",
            description="Search for files by name pattern and optionally content",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "pattern": {"type": "string", "default": "*"},
                    "content_pattern": {"type": "string"},
                    "max_results": {"type": "integer", "default": 100},
                },
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["filesystem", "read"],
        ),
        fs_search_handler,
    )