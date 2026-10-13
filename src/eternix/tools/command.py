import asyncio
import os
import shlex
from pathlib import Path
from typing import Any

from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.registry import tool_registry


async def cmd_exec_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    command = input_data.get("command")
    args = input_data.get("args", [])
    working_dir = input_data.get("working_dir")
    env = input_data.get("env", {})
    timeout = input_data.get("timeout", 60)
    shell = input_data.get("shell", False)

    if not command:
        return ToolResult(
            tool_id="cmd.exec",
            task_id=task.id,
            success=False,
            error="No command specified",
        )

    cwd = Path(working_dir).resolve() if working_dir else Path.cwd()
    full_env = {**os.environ, **env}

    try:
        if shell:
            cmd_str = command if not args else " ".join([command] + [shlex.quote(a) for a in args])
            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=full_env,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=full_env,
            )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return ToolResult(
                tool_id="cmd.exec",
                task_id=task.id,
                success=False,
                error=f"Command timed out after {timeout}s",
                stdout="",
                stderr="",
                exit_code=-1,
            )

        return ToolResult(
            tool_id="cmd.exec",
            task_id=task.id,
            success=exit_code == 0,
            output={"exit_code": exit_code},
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    except (TimeoutError, OSError) as e:
        return ToolResult(
            tool_id="cmd.exec",
            task_id=task.id,
            success=False,
            error=f"Failed to execute command: {e}",
        )


async def cmd_bg_start_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    command = input_data.get("command")
    args = input_data.get("args", [])
    working_dir = input_data.get("working_dir")
    env = input_data.get("env", {})
    name = input_data.get("name", "background_task")

    if not command:
        return ToolResult(
            tool_id="cmd.bg_start",
            task_id=task.id,
            success=False,
            error="No command specified",
        )

    cwd = Path(working_dir).resolve() if working_dir else Path.cwd()
    full_env = {**os.environ, **env}

    try:
        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=full_env,
            start_new_session=True,
        )

        return ToolResult(
            tool_id="cmd.bg_start",
            task_id=task.id,
            success=True,
            output={"pid": proc.pid, "name": name},
        )
    except (TimeoutError, OSError) as e:
        return ToolResult(
            tool_id="cmd.bg_start",
            task_id=task.id,
            success=False,
            error=f"Failed to start background process: {e}",
        )


async def cmd_bg_status_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    pid = input_data.get("pid")
    if not pid:
        return ToolResult(
            tool_id="cmd.bg_status",
            task_id=task.id,
            success=False,
            error="No PID specified",
        )

    try:
        os.kill(pid, 0)
        return ToolResult(
            tool_id="cmd.bg_status",
            task_id=task.id,
            success=True,
            output={"pid": pid, "running": True},
        )
    except ProcessLookupError:
        return ToolResult(
            tool_id="cmd.bg_status",
            task_id=task.id,
            success=True,
            output={"pid": pid, "running": False},
        )
    except (TimeoutError, OSError) as e:
        return ToolResult(
            tool_id="cmd.bg_status",
            task_id=task.id,
            success=False,
            error=f"Failed to check process: {e}",
        )


async def cmd_bg_stop_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    pid = input_data.get("pid")
    signal = input_data.get("signal", "SIGTERM")

    if not pid:
        return ToolResult(
            tool_id="cmd.bg_stop",
            task_id=task.id,
            success=False,
            error="No PID specified",
        )

    try:
        sig = getattr(__import__("signal"), signal)
        os.kill(pid, sig)
        return ToolResult(
            tool_id="cmd.bg_stop",
            task_id=task.id,
            success=True,
            output={"pid": pid},
        )
    except (TimeoutError, OSError) as e:
        return ToolResult(
            tool_id="cmd.bg_stop",
            task_id=task.id,
            success=False,
            error=f"Failed to stop process: {e}",
        )


def register_command_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="cmd.exec",
            name="Execute Command",
            description="Execute a command and capture output",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}, "default": []},
                    "working_dir": {"type": "string"},
                    "env": {"type": "object", "default": {}},
                    "timeout": {"type": "integer", "default": 60},
                    "shell": {"type": "boolean", "default": False},
                },
                "required": ["command"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=120,
            side_effect=ToolSideEffect.MODIFIES_SYSTEM,
            tags=["command", "exec"],
        ),
        cmd_exec_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="cmd.bg_start",
            name="Start Background Command",
            description="Start a command in the background",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}, "default": []},
                    "working_dir": {"type": "string"},
                    "env": {"type": "object", "default": {}},
                    "name": {"type": "string", "default": "background_task"},
                },
                "required": ["command"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.MODIFIES_SYSTEM,
            tags=["command", "background"],
        ),
        cmd_bg_start_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="cmd.bg_status",
            name="Check Background Command",
            description="Check status of a background process",
            input_schema={
                "type": "object",
                "properties": {"pid": {"type": "integer"}},
                "required": ["pid"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=5,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["command", "background"],
        ),
        cmd_bg_status_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="cmd.bg_stop",
            name="Stop Background Command",
            description="Stop a background process",
            input_schema={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer"},
                    "signal": {"type": "string", "default": "SIGTERM"},
                },
                "required": ["pid"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=5,
            side_effect=ToolSideEffect.MODIFIES_SYSTEM,
            tags=["command", "background"],
        ),
        cmd_bg_stop_handler,
    )