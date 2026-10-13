from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from eternix.auth.dependencies import require_active_account
from eternix.auth.routes import router as auth_router
from eternix.core.config import settings
from eternix.core.langgraph_orchestrator import LangGraphOrchestrator as Orchestrator
from eternix.core.models import (
    ConversationCreate,
    ConversationResponse,
    FileCreateRequest,
    FileDeleteRequest,
    FileWriteRequest,
    MessageCreate,
    Task,
    WorkspaceRegisterRequest,
)
from eternix.core.task_store import TaskStore, WorkspaceORM
from eternix.tools.registry import execute_tool, tool_registry

app = FastAPI(title="ETERNIX API", version="0.1.0")
orchestrator: Orchestrator | None = None
task_store: TaskStore | None = None

# Every protected route evaluates the mandatory gate centrally:
# valid session AND active account AND verified contact AND
# eligible payment method. The frontend never replaces this check.
PROTECTED = [Depends(require_active_account)]


@app.on_event("startup")
async def startup():
    global orchestrator, task_store
    task_store = TaskStore()
    orchestrator = Orchestrator(task_store)
    await orchestrator.initialize()
    from eternix import tools
    tools.register_filesystem_tools()
    tools.register_command_tools()
    tools.register_coding_tools()
    tools.register_document_tools()
    tools.register_data_tools()
    tools.register_web_tools()
    tools.register_memory_tools()
    tools.register_vision_tools()
    tools.register_audio_tools()
    tools.register_generation_tools()


@app.on_event("shutdown")
async def shutdown():
    global orchestrator
    if orchestrator is not None:
        try:
            await orchestrator.shutdown()
        except Exception:
            pass
        orchestrator = None


class ObjectiveRequest(BaseModel):
    user_input: str
    context: dict[str, Any] | None = None


class ObjectiveResponse(BaseModel):
    id: str
    user_input: str
    status: str


class TaskResponse(BaseModel):
    id: str
    objective_id: str
    description: str
    capability: str
    tool_id: str | None
    status: str
    error: str | None


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "capabilities": len(orchestrator.task_store.list_capabilities()) if orchestrator else 0,
    }


@app.get("/capabilities", dependencies=PROTECTED)
async def list_capabilities():
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    caps = orchestrator.task_store.list_capabilities()
    return [{"id": c.id, "name": c.name, "status": c.status.value, "tools": c.required_tools} for c in caps]


@app.get("/models", dependencies=PROTECTED)
async def list_models():
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    models = orchestrator.task_store.list_models()
    return [
        {
            "id": m.id,
            "name": m.name,
            "format": m.format,
            "size_bytes": m.size_bytes,
            "available": m.available,
            "capabilities": m.capabilities,
        }
        for m in models
    ]


@app.post("/objectives", response_model=ObjectiveResponse, dependencies=PROTECTED)
async def create_objective(request: ObjectiveRequest):
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    obj = await orchestrator.submit_objective(request.user_input, request.context)
    return ObjectiveResponse(id=str(obj.id), user_input=obj.user_input, status="created")


@app.get("/objectives/{objective_id}", dependencies=PROTECTED)
async def get_objective(objective_id: str):
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    try:
        oid = UUID(objective_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    obj = orchestrator.task_store.get_objective(oid)
    if not obj:
        raise HTTPException(404, "Objective not found")

    status = orchestrator.get_status(oid)
    return {
        "id": str(obj.id),
        "user_input": obj.user_input,
        "description": obj.description,
        "status": status,
    }


@app.get("/objectives/{objective_id}/tasks", dependencies=PROTECTED)
async def get_objective_tasks(objective_id: str):
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    try:
        oid = UUID(objective_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    tasks = orchestrator.task_store.get_tasks_for_objective(oid)
    return [
        TaskResponse(
            id=str(t.id),
            objective_id=str(t.objective_id),
            description=t.description,
            capability=t.capability,
            tool_id=t.tool_id,
            status=t.status.value,
            error=t.error,
        )
        for t in tasks
    ]


@app.post("/objectives/{objective_id}/run", dependencies=PROTECTED)
async def run_objective(objective_id: str):
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    try:
        oid = UUID(objective_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    result = await orchestrator.run_objective(oid)
    tasks = orchestrator.task_store.get_tasks_for_objective(oid)
    status = orchestrator.get_status(oid)
    status["_tasks"] = [
        {
            "id": str(t.id),
            "description": t.description,
            "capability": t.capability,
            "tool_id": t.tool_id,
            "status": t.status.value,
            "error": t.error,
            "input_data": t.input_data,
            "output_data": t.output_data,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in tasks
    ]
    return {"status": "completed", "details": status, "final_response": result.get("final_response", "")}


@app.post("/objectives/{objective_id}/stop", dependencies=PROTECTED)
async def stop_objective(objective_id: str):
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    try:
        oid = UUID(objective_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    await orchestrator.cancel_objective(oid)
    return {"status": "stopped"}


@app.get("/objectives/{objective_id}/events", dependencies=PROTECTED)
async def objective_events(objective_id: str):
    """Server-Sent Events endpoint for real-time task updates."""
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    try:
        oid = UUID(objective_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    async def event_generator():
        import asyncio
        import json

        last_status = None
        while True:
            try:
                tasks = orchestrator.task_store.get_tasks_for_objective(oid)
                status = orchestrator.get_status(oid)

                current_status = {
                    "tasks": [
                        {
                            "id": str(t.id),
                            "description": t.description,
                            "capability": t.capability,
                            "tool_id": t.tool_id,
                            "status": t.status.value,
                            "error": t.error,
                        }
                        for t in tasks
                    ],
                    "status": status,
                }

                if current_status != last_status:
                    yield f"data: {json.dumps(current_status)}\n\n"
                    last_status = current_status

                # Check if objective is complete
                if status["running"] == 0 and status["ready"] == 0 and status["total"] > 0:
                    yield f"data: {json.dumps({'complete': True, **current_status})}\n\n"
                    break

                await asyncio.sleep(1)
            except (asyncio.CancelledError, OSError, ValueError) as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/tools", dependencies=PROTECTED)
async def list_tools():
    tools = tool_registry.list_tools()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "tags": t.tags,
            "side_effect": t.side_effect.value,
        }
        for t in tools
    ]


@app.post("/tools/{tool_id}/execute", dependencies=PROTECTED)
async def execute_tool_route(tool_id: str, input_data: dict[str, Any]):
    if not orchestrator:
        raise HTTPException(503, "Not initialized")

    tool_def = tool_registry.get(tool_id)
    if not tool_def:
        raise HTTPException(404, "Tool not found")

    task = Task(id=uuid4(), objective_id=uuid4(), description="API Tool Test", capability="test", tool_id=tool_id, input_data=input_data)
    result = await execute_tool(tool_id, task, input_data, orchestrator.task_store)

    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
    }


# Serve static frontend files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _workspace_root() -> Path:
    """The active workspace root confines file operations."""
    if task_store is None:
        return Path.cwd().resolve()
    with task_store.session() as s:
        ws = s.scalars(select(WorkspaceORM).where(WorkspaceORM.active == 1)).first()
        if ws:
            return Path(ws.path).resolve()
    return Path.cwd().resolve()


def _confine(path: Path, root: Path) -> Path:
    """Canonicalize and verify a path stays inside the workspace root."""
    candidate = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if root != candidate and root not in candidate.parents:
        raise HTTPException(403, "Path is outside the authorized workspace")
    return candidate


@app.get("/workspace/browse", dependencies=PROTECTED)
async def browse_workspace(path: str | None = None):
    root = _workspace_root()
    target = _confine(Path(path) if path else root, root)
    if target.is_file():
        return [{"name": target.name, "path": str(target), "type": "file", "size": target.stat().st_size}]
    items = []
    try:
        for p in sorted(target.iterdir())[:200]:
            items.append({
                "name": p.name,
                "path": str(p),
                "type": "directory" if p.is_dir() else "file",
                "size": p.stat().st_size if p.is_file() else 0,
            })
    except Exception as e:
        raise HTTPException(400, str(e))
    return items


@app.get("/workspace/read", dependencies=PROTECTED)
async def read_workspace_file(path: str):
    root = _workspace_root()
    p = _confine(Path(path), root)
    if not p.exists():
        raise HTTPException(404, "Not found")
    try:
        content = p.read_text(encoding='utf-8', errors='replace')
    except Exception:
        content = p.read_bytes().decode('latin-1', errors='replace')
    return {"content": content, "language": None, "size": len(content), "path": str(p)}


async def _run_tool(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute a registered tool and return its real result."""
    if not orchestrator:
        raise HTTPException(503, "Not initialized")
    if not tool_registry.get(tool_id):
        raise HTTPException(404, f"Tool not found: {tool_id}")
    task = Task(id=uuid4(), objective_id=uuid4(), description="API request", capability="api", tool_id=tool_id, input_data=input_data)
    result = await execute_tool(tool_id, task, input_data, orchestrator.task_store)
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
    }


@app.post("/intelligence/search", dependencies=PROTECTED)
async def intelligence_search(payload: dict[str, Any] | None = None):
    body = payload or {}
    query = body.get("query", "")
    path = body.get("path", ".")
    return await _run_tool("coding.search", {"query": query, "path": path})


@app.get("/intelligence/index", dependencies=PROTECTED)
async def intelligence_index_status():
    return {"status": "idle"}


@app.post("/intelligence/index", dependencies=PROTECTED)
async def intelligence_index(path: str = "."):
    return {"status": "ok", "message": "indexed", "path": path}


@app.get("/intelligence/status", dependencies=PROTECTED)
async def intelligence_status():
    return {"status": "idle"}


@app.post("/research/search", dependencies=PROTECTED)
async def research_search(payload: dict[str, Any] | None = None):
    body = payload or {}
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "query is required")
    result = await _run_tool("web.search", {"query": query})
    results = result.output.get("results", []) if result.output else []
    citations = [
        {"title": r.get("title"), "url": r.get("url"), "source": r.get("source"), "snippet": r.get("snippet")}
        for r in results
    ]
    return {"query": query, "results": results, "citations": citations, "tool_error": result.error}


@app.get("/research/history", dependencies=PROTECTED)
async def research_history():
    return []


@app.post("/knowledge/search", dependencies=PROTECTED)
async def knowledge_search(payload: dict[str, Any] | None = None):
    body = payload or {}
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "query is required")
    result = await _run_tool("memory.search", {"query": query})
    return {"results": result.output.get("results", []) if result.output else [], "output": result.output, "tool_error": result.error}


@app.post("/execution/run", dependencies=PROTECTED)
async def execution_run(payload: dict[str, Any] | None = None):
    body = payload or {}
    command = body.get("command", "")
    if not command:
        raise HTTPException(400, "command is required")
    cwd = body.get("cwd") or body.get("working_dir")
    timeout = body.get("timeout", 60)
    return await _run_tool("cmd.exec", {"command": command, "args": [], "working_dir": cwd, "timeout": timeout})


@app.get("/conversations", response_model=list[ConversationResponse], dependencies=PROTECTED)
async def list_conversations():
    if not task_store:
        raise HTTPException(503, "Not initialized")
    return task_store.list_conversations()


@app.get("/conversations/{conversation_id}", dependencies=PROTECTED)
async def get_conversation(conversation_id: str):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    conv = task_store.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@app.delete("/conversations/{conversation_id}", dependencies=PROTECTED)
async def delete_conversation(conversation_id: str):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    if task_store.delete_conversation(conversation_id):
        return {"status": "ok"}
    raise HTTPException(404, "Conversation not found")


@app.patch("/conversations/{conversation_id}", dependencies=PROTECTED)
async def rename_conversation(conversation_id: str, request: dict[str, Any]):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    title = request.get("title", "")
    result = task_store.rename_conversation(conversation_id, title)
    if not result:
        raise HTTPException(404, "Conversation not found")
    return result


@app.get("/artifacts", dependencies=PROTECTED)
async def list_artifacts(objective_id: str | None = None):
    return []


@app.get("/system", dependencies=PROTECTED)
async def system_info():
    import os
    import platform

    import psutil
    return {
        "platform": platform.system(),
        "version": platform.release(),
        "memory_total": psutil.virtual_memory().total,
        "cpu_count": os.cpu_count(),
        "disk_usage": {},
        "python_version": platform.python_version(),
    }


@app.post("/conversations", response_model=ConversationResponse, dependencies=PROTECTED)
async def create_conversation(request: ConversationCreate):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    oid = UUID(request.objective_id) if request.objective_id else None
    conv_id, title = task_store.create_conversation(request.title, oid)
    return ConversationResponse(id=conv_id, title=title, objective_id=request.objective_id)


@app.post("/conversations/{conversation_id}/messages", dependencies=PROTECTED)
async def add_message(conversation_id: str, request: MessageCreate):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    msg_id = task_store.add_message(conversation_id, request.role, request.content)
    return {"id": msg_id, "conversation_id": conversation_id}


@app.post("/workspace/register", dependencies=PROTECTED)
async def register_workspace(request: WorkspaceRegisterRequest):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    p = Path(request.path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f"Path does not exist or is not a directory: {request.path}")
    name = request.name or p.name
    return task_store.create_workspace(name, str(p.resolve()))


@app.get("/workspace/list", dependencies=PROTECTED)
async def list_workspaces():
    if not task_store:
        raise HTTPException(503, "Not initialized")
    return task_store.list_workspaces()


@app.post("/workspace/set-active", dependencies=PROTECTED)
async def set_active_workspace(request: WorkspaceRegisterRequest):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    p = Path(request.path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f"Path does not exist or is not a directory: {request.path}")
    # Find by path
    with task_store.session() as s:
        ws = s.scalars(select(WorkspaceORM).where(WorkspaceORM.path == str(p.resolve()))).first()
        if ws:
            task_store.set_active_workspace(ws.id)
            return {"id": ws.id, "name": ws.name, "path": ws.path, "active": True}
    raise HTTPException(404, "Workspace not registered")


@app.delete("/workspace/{workspace_id}", dependencies=PROTECTED)
async def delete_workspace(workspace_id: str):
    if not task_store:
        raise HTTPException(503, "Not initialized")
    if task_store.delete_workspace(workspace_id):
        return {"status": "ok"}
    raise HTTPException(404, "Workspace not found")


@app.post("/files/write", dependencies=PROTECTED)
async def write_file(request: FileWriteRequest):
    root = _workspace_root()
    p = _confine(Path(request.path), root)
    parent = p.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    p.write_text(request.content, encoding='utf-8')
    return {"status": "ok", "path": str(p), "size": len(request.content)}


@app.post("/files/create", dependencies=PROTECTED)
async def create_file(request: FileCreateRequest):
    root = _workspace_root()
    p = _confine(Path(request.path), root)
    parent = p.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise HTTPException(409, f"File already exists: {request.path}")
    p.write_text(request.content, encoding='utf-8')
    return {"status": "ok", "path": str(p)}


@app.post("/files/delete", dependencies=PROTECTED)
async def delete_file(request: FileDeleteRequest):
    root = _workspace_root()
    p = _confine(Path(request.path), root)
    if not p.exists():
        raise HTTPException(404, "File not found")
    if p.is_dir():
        import shutil
        shutil.rmtree(p)
    else:
        p.unlink()
    return {"status": "ok", "path": str(p)}


@app.post("/files/move", dependencies=PROTECTED)
async def move_file(payload: dict[str, Any]):
    root = _workspace_root()
    src = _confine(Path(payload["src"]), root)
    dst = _confine(Path(payload["dst"]), root)
    if not src.exists():
        raise HTTPException(404, "Source not found")
    dst.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.move(str(src), str(dst))
    return {"status": "ok", "src": str(src), "dst": str(dst)}


# Authentication routes are mounted at the root and under /api so the
# frontend client and the SPA share one authoritative contract.
app.include_router(auth_router)
app.include_router(auth_router, prefix="/api")


def _register_api_aliases() -> None:
    """Expose the same API contract under /api in addition to the root routes.

    The frontend client is authored against the /api namespace, while the
    backend historically served routes at the root. Registering aliases keeps
    the existing API behavior without breaking older callers and ensures the
    browser shell can actually load data.
    """
    aliases = [
        ("/health", health, ["GET"], []),
        ("/capabilities", list_capabilities, ["GET"], PROTECTED),
        ("/models", list_models, ["GET"], PROTECTED),
        ("/objectives", create_objective, ["POST"], PROTECTED),
        ("/objectives/{objective_id}", get_objective, ["GET"], PROTECTED),
        ("/objectives/{objective_id}/tasks", get_objective_tasks, ["GET"], PROTECTED),
        ("/objectives/{objective_id}/run", run_objective, ["POST"], PROTECTED),
        ("/objectives/{objective_id}/stop", stop_objective, ["POST"], PROTECTED),
        ("/objectives/{objective_id}/events", objective_events, ["GET"], PROTECTED),
        ("/tools", list_tools, ["GET"], PROTECTED),
        ("/tools/{tool_id}/execute", execute_tool_route, ["POST"], PROTECTED),
        ("/workspace/browse", browse_workspace, ["GET"], PROTECTED),
        ("/workspace/read", read_workspace_file, ["GET"], PROTECTED),
        ("/intelligence/search", intelligence_search, ["POST"], PROTECTED),
        ("/intelligence/index", intelligence_index, ["POST"], PROTECTED),
        ("/intelligence/status", intelligence_status, ["GET"], PROTECTED),
        ("/research/search", research_search, ["POST"], PROTECTED),
        ("/research/history", research_history, ["GET"], PROTECTED),
        ("/knowledge/search", knowledge_search, ["POST"], PROTECTED),
        ("/execution/run", execution_run, ["POST"], PROTECTED),
        ("/conversations", list_conversations, ["GET"], PROTECTED),
        ("/conversations/{conversation_id}", get_conversation, ["GET"], PROTECTED),
        ("/conversations/{conversation_id}", delete_conversation, ["DELETE"], PROTECTED),
        ("/conversations/{conversation_id}", rename_conversation, ["PATCH"], PROTECTED),
        ("/artifacts", list_artifacts, ["GET"], PROTECTED),
        ("/system", system_info, ["GET"], PROTECTED),
        ("/conversations", create_conversation, ["POST"], PROTECTED),
        ("/conversations/{conversation_id}/messages", add_message, ["POST"], PROTECTED),
        ("/workspace/register", register_workspace, ["POST"], PROTECTED),
        ("/workspace/list", list_workspaces, ["GET"], PROTECTED),
        ("/workspace/set-active", set_active_workspace, ["POST"], PROTECTED),
        ("/workspace/{workspace_id}", delete_workspace, ["DELETE"], PROTECTED),
        ("/files/write", write_file, ["POST"], PROTECTED),
        ("/files/create", create_file, ["POST"], PROTECTED),
        ("/files/delete", delete_file, ["POST"], PROTECTED),
        ("/files/move", move_file, ["POST"], PROTECTED),
    ]

    for path, endpoint, methods, dependencies in aliases:
        app.router.add_api_route(
            f"/api{path}",
            endpoint,
            methods=methods,
            dependencies=dependencies,
        )


_register_api_aliases()


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve the SPA for all non-API routes."""
    static_dir = Path(__file__).parent.parent / "static"
    index_file = static_dir / "index.html"

    if index_file.exists():
        return FileResponse(index_file)

    # Fallback if frontend not built
    return Response(
        content="""
<!DOCTYPE html>
<html>
<head>
    <title>ETERNIX - Building...</title>
    <style>
        body { font-family: system-ui; background: #0c1e33; color: #e8edf2; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .container { text-align: center; }
        .logo { width: 80px; height: 80px; border-radius: 16px; background: linear-gradient(135deg, #486581, #627d98); display: inline-flex; align-items: center; justify-content: center; margin-bottom: 24px; }
        .spinner { width: 40px; height: 40px; border: 3px solid #1e3a5f; border-top-color: #486581; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 24px; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h12M6 12h12M6 16h8"/></svg></div>
        <div class="spinner"></div>
        <h1>ETERNIX</h1>
        <p style="color: #829ab1;">Frontend building... Please wait.</p>
    </div>
</body>
</html>
        """,
        media_type="text/html",
    )
