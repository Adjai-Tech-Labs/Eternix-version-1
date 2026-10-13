from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from eternix.core.models import Task, ToolDefinition, ToolResult
from eternix.core.task_store import TaskStore


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable] = {}

    def register(self, tool: ToolDefinition, handler: Callable) -> None:
        self._tools[tool.id] = tool
        self._handlers[tool.id] = handler

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def get_handler(self, tool_id: str) -> Callable | None:
        return self._handlers.get(tool_id)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_by_tag(self, tag: str) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if tag in t.tags]

    def get_for_capability(self, capability: str) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if capability in t.tags]


tool_registry = ToolRegistry()


async def execute_tool(
    tool_id: str,
    task: Task,
    input_data: dict[str, Any],
    task_store: TaskStore,
) -> ToolResult:
    import time

    handler = tool_registry.get_handler(tool_id)
    if not handler:
        return ToolResult(
            tool_id=tool_id,
            task_id=task.id,
            success=False,
            error=f"Tool {tool_id} not found",
        )

    tool_registry.get(tool_id)

    start = time.time()
    started_at = datetime.now(UTC)

    try:
        result = await handler(input_data, task, task_store)
        duration_ms = int((time.time() - start) * 1000)
        completed_at = datetime.now(UTC)

        if isinstance(result, ToolResult):
            result.duration_ms = duration_ms
            result.started_at = started_at
            result.completed_at = completed_at
            return result

        return ToolResult(
            tool_id=tool_id,
            task_id=task.id,
            success=True,
            output=result if isinstance(result, dict) else {"result": str(result)},
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=completed_at,
        )
    except (RuntimeError, ValueError, OSError) as e:
        duration_ms = int((time.time() - start) * 1000)
        completed_at = datetime.now(UTC)
        return ToolResult(
            tool_id=tool_id,
            task_id=task.id,
            success=False,
            error=str(e),
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=completed_at,
        )