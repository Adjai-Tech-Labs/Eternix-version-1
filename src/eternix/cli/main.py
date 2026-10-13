import asyncio
import json
from uuid import UUID

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from eternix.core.config import ensure_dirs, settings
from eternix.core.models import CapabilityStatus, TaskStatus
from eternix.core.orchestrator import Orchestrator
from eternix.core.task_store import TaskStore

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """ETERNIX - Autonomous AI Agent"""
    ensure_dirs()


@cli.command()
@click.argument("objective", required=False)
@click.option("--file", "-f", multiple=True, help="Attach file to objective context")
@click.option("--interactive", "-i", is_flag=True, help="Run in interactive mode")
def run(objective: str | None, file: tuple, interactive: bool):
    """Run an objective"""
    async def _run():
        orchestrator = Orchestrator()
        await orchestrator.initialize()

        if interactive or not objective:
            console.print(Panel.fit("ETERNIX Interactive Mode", style="bold blue"))
            console.print("Enter objectives (Ctrl+C to exit):\n")

            while True:
                try:
                    user_input = console.input("[bold cyan]eternix>[/bold cyan] ")
                    if not user_input.strip():
                        continue
                    if user_input.lower() in ("exit", "quit"):
                        break

                    obj = await orchestrator.submit_objective(user_input)
                    console.print(f"[green]Submitted objective:[/green] {obj.id}")
                    await orchestrator.run_objective(obj.id)
                    status = orchestrator.get_status(obj.id)
                    console.print(f"[green]Completed:[/green] {status['completed']}/{status['total']} tasks")

                except KeyboardInterrupt:
                    break
                except (RuntimeError, ValueError, OSError) as e:
                    console.print(f"[red]Error:[/red] {e}")
        else:
            context = {"files": list(file)} if file else None
            obj = await orchestrator.submit_objective(objective, context)
            console.print(f"[green]Submitted objective:[/green] {obj.id}")
            await orchestrator.run_objective(obj.id)
            status = orchestrator.get_status(obj.id)
            console.print(f"[green]Completed:[/green] {status['completed']}/{status['total']} tasks")

    asyncio.run(_run())


@cli.command()
@click.argument("objective_id", type=str)
def status(objective_id: str):
    """Check objective status"""
    try:
        oid = UUID(objective_id)
    except ValueError:
        console.print("[red]Invalid UUID[/red]")
        return

    task_store = TaskStore()
    tasks = task_store.get_tasks_for_objective(oid)

    if not tasks:
        console.print("[yellow]No tasks found for objective[/yellow]")
        return

    table = Table(title=f"Objective {objective_id}")
    table.add_column("Task ID", style="cyan")
    table.add_column("Description")
    table.add_column("Capability")
    table.add_column("Tool")
    table.add_column("Status", style="bold")
    table.add_column("Attempts")

    for task in tasks:
        status_style = {
            TaskStatus.COMPLETED: "green",
            TaskStatus.FAILED: "red",
            TaskStatus.RUNNING: "yellow",
            TaskStatus.READY: "blue",
            TaskStatus.RECOVERING: "magenta",
        }.get(task.status, "white")

        table.add_row(
            str(task.id)[:8],
            task.description[:50],
            task.capability,
            task.tool_id or "-",
            f"[{status_style}]{task.status.value}[/{status_style}]",
            str(task.attempts),
        )

    console.print(table)


@cli.command()
def capabilities():
    """List available capabilities"""
    task_store = TaskStore()
    caps = task_store.list_capabilities()

    table = Table(title="Capabilities")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Status", style="bold")
    table.add_column("Tools")

    for cap in caps:
        status_style = {
            CapabilityStatus.AVAILABLE: "green",
            CapabilityStatus.INSTALLED_UNVERIFIED: "yellow",
            CapabilityStatus.MISSING: "red",
            CapabilityStatus.WAITING_MODEL: "blue",
            CapabilityStatus.WAITING_CREDENTIAL: "magenta",
            CapabilityStatus.FAILED_INIT: "red",
        }.get(cap.status, "white")

        table.add_row(
            cap.id,
            cap.name,
            f"[{status_style}]{cap.status.value}[/{status_style}]",
            ", ".join(cap.required_tools) if cap.required_tools else "-",
        )

    console.print(table)


@cli.command()
def models():
    """List discovered models"""
    task_store = TaskStore()
    models = task_store.list_models()

    table = Table(title="Models")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Format")
    table.add_column("Size")
    table.add_column("Available", style="bold")

    for model in models:
        size_mb = model.size_bytes / (1024 * 1024)
        table.add_row(
            model.id[:30],
            model.name[:40],
            model.format,
            f"{size_mb:.1f} MB",
            "[green]Yes[/green]" if model.available else "[red]No[/red]",
        )

    console.print(table)


@cli.command()
@click.argument("tool_id")
@click.option("--input", "-i", "input_json", help="JSON input for tool")
def tool(tool_id: str, input_json: str | None):
    """Test a tool directly"""
    from uuid import uuid4

    from eternix.core.models import Task
    from eternix.tools.registry import execute_tool, tool_registry

    async def _run_tool():
        from eternix.tools import (
            register_audio_tools,
            register_coding_tools,
            register_command_tools,
            register_data_tools,
            register_document_tools,
            register_filesystem_tools,
            register_memory_tools,
            register_vision_tools,
            register_web_tools,
        )
        register_filesystem_tools()
        register_command_tools()
        register_document_tools()
        register_data_tools()
        register_web_tools()
        register_coding_tools()
        register_vision_tools()
        register_audio_tools()
        register_memory_tools()

        task_store = TaskStore()
        tool_def = tool_registry.get(tool_id)

        if not tool_def:
            console.print(f"[red]Tool not found: {tool_id}[/red]")
            console.print("Available tools:")
            for t in tool_registry.list_tools():
                console.print(f"  {t.id}")
            return

        input_data = json.loads(input_json) if input_json else {}
        task = Task(id=uuid4(), objective_id=uuid4(), description="Test", capability="test", tool_id=tool_id, input_data=input_data)

        console.print(f"[cyan]Running tool:[/cyan] {tool_id}")
        result = await execute_tool(tool_id, task, input_data, task_store)

        if result.success:
            console.print("[green]Success![/green]")
            console.print(json.dumps({
                "output": result.output,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            }, indent=2))
        else:
            console.print("[red]Failed![/red]")
            console.print(result.error)

    asyncio.run(_run_tool())


@cli.command()
def serve():
    """Start the API server"""
    import uvicorn

    from eternix.api.server import app

    console.print(f"[green]Starting API server on {settings.api_host}:{settings.api_port}[/green]")
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


@cli.command()
def init():
    """Initialize ETERNIX data directories and database"""
    ensure_dirs()
    TaskStore()
    orchestrator = Orchestrator()
    asyncio.run(orchestrator.initialize())
    console.print("[green]ETERNIX initialized successfully![/green]")


if __name__ == "__main__":
    cli()