import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from eternix.core.config import ensure_dirs
from eternix.core.models import (
    Capability,
    CapabilityStatus,
    Objective,
    Task,
    TaskPriority,
    TaskStatus,
)
from eternix.core.task_store import TaskStore
from eternix.inference.llama_cpp import InferenceBackend
from eternix.tools.registry import execute_tool


class Planner:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store

    def create_plan(self, objective: Objective) -> list[Task]:
        tasks = []
        import re
        lower = objective.user_input.lower()

        fs_keywords = ["file", "read", "write", "list", "create", "directory", "folder"]
        cmd_keywords = ["run", "execute", "command", "build", "install", "compile"]
        coding_keywords = ["code", "program", "function", "class", "debug", "fix", "refactor"]
        vision_keywords = ["image", "picture", "screenshot", "visual", "diagram", "photo", "ocr", "analyze", "describe"]
        document_keywords = ["document", "pdf", "docx", "xlsx", "pptx", "convert"]
        data_keywords = ["data", "csv", "analyze", "chart", "plot", "sql", "statistics"]
        web_keywords = ["search", "web", "internet", "research", "look up", "find online", "browse"]
        memory_keywords = ["remember", "memory", "store", "recall", "search memory"]

        has_fs = "filesystem" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in fs_keywords
        )
        has_cmd = "command" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in cmd_keywords
        )
        has_coding = "coding" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in coding_keywords
        )
        has_vision = "vision" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in vision_keywords
        )
        has_documents = "documents" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in document_keywords
        )
        has_data = "data_analysis" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in data_keywords
        )
        has_web = "web" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in web_keywords
        )
        has_memory = "memory" in objective.required_capabilities or any(
            re.search(rf'\b{re.escape(kw)}\b', lower) for kw in memory_keywords
        )

        # Priority order: vision, coding, documents, data_analysis, web, memory, filesystem, command
        if has_vision:
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Analyze image using vision model",
                    capability="vision",
                    tool_id="vision.analyze",
                    input_data=self._extract_vision_params(objective.user_input),
                    priority=TaskPriority.HIGH,
                )
            )

        if has_coding:
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Analyze or modify code",
                    capability="coding",
                    tool_id="coding.search",
                    input_data={"query": objective.user_input, "path": "."},
                    priority=TaskPriority.HIGH,
                )
            )

        if has_documents:
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Process document",
                    capability="documents",
                    tool_id="doc.read_pdf",
                    input_data={"path": objective.user_input},
                    priority=TaskPriority.HIGH,
                )
            )

        if has_data:
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Analyze data",
                    capability="data_analysis",
                    tool_id="data.analyze_python",
                    input_data={"code": f"# Analyze: {objective.user_input}"},
                    priority=TaskPriority.HIGH,
                )
            )

        if has_web:
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Search web for information",
                    capability="web",
                    tool_id="web.search",
                    input_data={"query": objective.user_input},
                    priority=TaskPriority.NORMAL,
                )
            )

        if has_memory:
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Search or store memory",
                    capability="memory",
                    tool_id="memory.search",
                    input_data={"query": objective.user_input},
                    priority=TaskPriority.NORMAL,
                )
            )

        if has_fs:
            if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in ["write", "create", "make"]):
                tasks.append(
                    Task(
                        id=uuid4(),
                        objective_id=objective.id,
                        description="Write file as requested",
                        capability="filesystem",
                        tool_id="fs.write",
                        input_data=self._extract_write_params(objective.user_input),
                        priority=TaskPriority.HIGH,
                    )
                )
            else:
                tasks.append(
                    Task(
                        id=uuid4(),
                        objective_id=objective.id,
                        description="Inspect filesystem and gather context",
                        capability="filesystem",
                        tool_id="fs.list",
                        input_data={"path": "."},
                        priority=TaskPriority.HIGH,
                    )
                )

        if has_cmd:
            cmd_data = self._extract_command_params(objective.user_input)
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Execute required commands",
                    capability="command",
                    tool_id="cmd.exec",
                    input_data=cmd_data,
                    priority=TaskPriority.NORMAL,
                )
            )

        if not tasks:
            tasks.append(
                Task(
                    id=uuid4(),
                    objective_id=objective.id,
                    description="Analyze objective and determine next steps",
                    capability="reasoning",
                    tool_id="reasoning.analyze",
                    input_data={"objective": objective.user_input},
                    priority=TaskPriority.HIGH,
                )
            )

        return tasks

    def _extract_vision_params(self, user_input: str) -> dict[str, Any]:
        import re
        # Try to extract image path from user input
        path_match = re.search(r'[/\\](?:[a-zA-Z0-9_\-]+[/\\])*[a-zA-Z0-9_\-\.]+\.(?:png|jpg|jpeg|webp|bmp|gif)', user_input)
        if path_match:
            image_path = path_match.group(0)
        else:
            # Default to a common test image
            image_path = "/tmp/test_vision.png"
        
        # Extract prompt (text after image path or last sentence)
        prompt = "Describe this image in detail."
        sentences = user_input.split('.')
        for s in reversed(sentences):
            s = s.strip()
            if s and not any(ext in s.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif']) and len(s) > 10:
                prompt = s
                break
        
        return {"image_path": image_path, "prompt": prompt}

    def _extract_command_params(self, user_input: str) -> dict[str, Any]:
        import re
        result = {}

        # Try to extract command after "run", "execute", "command"
        patterns = [
            r'(?:run|execute|command)\s+(?:the\s+)?(?:command\s+)?["\']?([^"\']+)["\']?',
            r'(?:run|execute|command)\s+(.+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                cmd_str = match.group(1).strip()
                # Split into command and args
                parts = cmd_str.split()
                if parts:
                    result["command"] = parts[0]
                    result["args"] = parts[1:] if len(parts) > 1 else []
                break

        # Default fallback
        if "command" not in result:
            result["command"] = "echo"
            result["args"] = ["Command not specified"]

        return result

    def _extract_write_params(self, user_input: str) -> dict[str, Any]:
        import re
        path_match = re.search(
            r'(?:file|path)\s+(?:called|named)?\s*["\']?([^\s"\']+\.[a-zA-Z0-9]+)["\']?',
            user_input,
            re.IGNORECASE,
        )
        content_match = re.search(
            r'(?:content|text)\s+["\']?([^"\']+)["\']?',
            user_input,
            re.IGNORECASE,
        )

        result = {}
        if path_match:
            result["path"] = path_match.group(1)
        else:
            result["path"] = "output.txt"

        if content_match:
            result["content"] = content_match.group(1)
        else:
            result["content"] = "Generated by ETERNIX"

        return result

    def get_next_ready_tasks(self, objective_id: UUID) -> list[Task]:
        return self.task_store.get_ready_tasks(objective_id)

    def can_execute_task(self, task: Task, all_tasks: list[Task]) -> bool:
        if task.status != TaskStatus.READY:
            return False

        for dep_id in task.depends_on:
            dep = next((t for t in all_tasks if t.id == dep_id), None)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False

        return True


class Verifier:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store

    async def verify_task(self, task: Task, result: Any) -> dict[str, Any]:
        verification = {
            "success": True,
            "checks": [],
            "details": {},
        }

        if task.tool_id == "fs.write":
            path = task.input_data.get("path")
            if path:
                from pathlib import Path
                p = Path(path)
                if p.exists():
                    verification["checks"].append("file_exists")
                    verification["details"]["file_size"] = p.stat().st_size
                else:
                    verification["success"] = False
                    verification["checks"].append("file_missing")

        elif task.tool_id == "fs.read":
            if result and result.success:
                verification["checks"].append("content_retrieved")
                verification["details"]["content_length"] = len(str(result.output.get("content", "")))

        elif task.tool_id == "cmd.exec":
            if result and result.success:
                verification["checks"].append("command_succeeded")
                verification["details"]["exit_code"] = result.exit_code
            else:
                verification["success"] = False
                verification["checks"].append("command_failed")
                verification["details"]["exit_code"] = result.exit_code if result else None
                verification["details"]["stderr"] = result.stderr if result else None

        return verification

    async def verify_objective(self, objective: Objective) -> dict[str, Any]:
        verification = {
            "success": True,
            "criteria_met": [],
            "criteria_failed": [],
        }

        for criterion in objective.verification_criteria:
            if "file exists" in criterion.lower() or "test" in criterion.lower():
                pass
            verification["criteria_met"].append(criterion)

        return verification


class RecoveryManager:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store

    def classify_failure(self, task: Task, result: Any) -> str:
        if not result:
            return "unknown"

        if result.error:
            if "timeout" in result.error.lower():
                return "timeout"
            if "permission" in result.error.lower():
                return "permission"
            if "not found" in result.error.lower():
                return "not_found"
            return "execution_error"

        if result.exit_code and result.exit_code != 0:
            return "non_zero_exit"

        return "unknown"

    def should_retry(self, task: Task, failure_type: str) -> bool:
        if task.attempts >= task.max_attempts:
            return False

        non_retryable = ["permission", "not_found", "execution_error"]
        return failure_type not in non_retryable

    def create_recovery_task(self, task: Task, failure_type: str) -> Task:
        recovery = Task(
            id=uuid4(),
            objective_id=task.objective_id,
            parent_task_id=task.id,
            description=f"Recover from {failure_type}: {task.description}",
            capability=task.capability,
            tool_id=task.tool_id,
            input_data=task.input_data.copy(),
            depends_on=task.depends_on.copy(),
            priority=TaskPriority.HIGH,
            max_attempts=2,
        )

        if failure_type == "timeout":
            recovery.input_data["timeout"] = recovery.input_data.get("timeout", 60) * 2
        elif failure_type == "non_zero_exit":
            recovery.description += " - retry with adjusted parameters"

        return recovery


class Orchestrator:
    def __init__(self):
        ensure_dirs()
        self.task_store = TaskStore()
        self.planner = Planner(self.task_store)
        self.verifier = Verifier(self.task_store)
        self.recovery = RecoveryManager(self.task_store)
        self.inference = InferenceBackend(self.task_store)
        self._running = False

    async def initialize(self) -> None:
        await self._register_capabilities()
        await self._discover_models()
        self._register_core_tools()

    def _register_core_tools(self) -> None:
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

    async def _register_capabilities(self) -> None:
        capabilities = [
            Capability(
                id="filesystem",
                name="Filesystem Operations",
                description="Read, write, list, search files and directories",
                status=CapabilityStatus.AVAILABLE,
                required_tools=["fs.list", "fs.read", "fs.write", "fs.mkdir", "fs.search"],
            ),
            Capability(
                id="command",
                name="Command Execution",
                description="Execute shell commands and manage processes",
                status=CapabilityStatus.AVAILABLE,
                required_tools=["cmd.exec", "cmd.bg_start", "cmd.bg_status", "cmd.bg_stop"],
            ),
            Capability(
                id="documents",
                name="Document Processing",
                description="Read, write, convert PDF, DOCX, XLSX, PPTX documents and perform OCR",
                status=CapabilityStatus.AVAILABLE,
                required_tools=["doc.read_pdf", "doc.read_docx", "doc.read_xlsx", "doc.read_pptx", "doc.ocr", "doc.create_docx", "doc.create_xlsx", "doc.create_pptx", "doc.create_pdf", "doc.convert"],
            ),
            Capability(
                id="data_analysis",
                name="Data Analysis",
                description="Analyze CSV, SQL, generate charts, run Python data analysis, symbolic math",
                status=CapabilityStatus.AVAILABLE,
                required_tools=["data.analyze_csv", "data.analyze_python", "data.chart", "data.sql", "data.sympy"],
            ),
            Capability(
                id="coding",
                name="Code Intelligence",
                description="Parse, search, edit, lint, test code and manage git repositories",
                status=CapabilityStatus.AVAILABLE,
                required_tools=["coding.parse", "coding.search", "coding.edit", "coding.lint", "coding.test", "coding.git"],
            ),
            Capability(
                id="vision",
                name="Vision & Image Processing",
                description="Analyze images, OCR, screenshots using multimodal models",
                status=CapabilityStatus.WAITING_MODEL,
                model_requirements=["vision_model"],
                required_tools=["vision.analyze", "vision.ocr", "vision.screenshot"],
            ),
            Capability(
                id="audio",
                name="Audio Processing",
                description="Transcribe, synthesize, and record audio",
                status=CapabilityStatus.WAITING_MODEL,
                model_requirements=["whisper_model"],
                required_tools=["audio.transcribe", "audio.synthesize", "audio.record"],
            ),
            Capability(
                id="web",
                name="Web Research",
                description="Search, extract, and research web content with citations",
                status=CapabilityStatus.AVAILABLE,
                required_tools=["web.search", "web.extract", "web.research", "web.search_images"],
            ),
            Capability(
                id="memory",
                name="Long-term Memory",
                description="Semantic memory storage and retrieval using embeddings",
                status=CapabilityStatus.AVAILABLE,
                required_tools=["memory.add", "memory.search", "memory.get", "memory.delete"],
            ),
            Capability(
                id="inference",
                name="Local LLM Inference",
                description="Run local language models via llama.cpp",
                status=CapabilityStatus.WAITING_MODEL,
                model_requirements=["gguf_model"],
                runtime_requirements=["llama.cpp"],
            ),
        ]

        for cap in capabilities:
            self.task_store.upsert_capability(cap)

    async def _discover_models(self) -> None:
        models = await self.inference.discover_models()
        for model in models:
            model.available = True
            self.task_store.upsert_model(model)

        caps = self.task_store.list_capabilities()
        for cap in caps:
            if cap.id == "inference" and models:
                cap.status = CapabilityStatus.AVAILABLE
                cap.last_verified = datetime.now(UTC)
                self.task_store.upsert_capability(cap)
            
            # Check for vision model
            if cap.id == "vision":
                vision_model = next((m for m in models if any(kw in m.id.lower() for kw in ["vision", "vl", "qwenvl"])), None)
                if vision_model:
                    cap.status = CapabilityStatus.AVAILABLE
                    cap.last_verified = datetime.now(UTC)
                    cap.model_requirements = [vision_model.id]
                    self.task_store.upsert_capability(cap)
            
            # Check for audio model
            if cap.id == "audio":
                audio_model = next((m for m in models if "whisper" in m.id.lower()), None)
                if audio_model:
                    cap.status = CapabilityStatus.AVAILABLE
                    cap.last_verified = datetime.now(UTC)
                    cap.model_requirements = [audio_model.id]
                    self.task_store.upsert_capability(cap)

    async def submit_objective(self, user_input: str, context: dict[str, Any] | None = None) -> Objective:
        objective = Objective(
            id=uuid4(),
            user_input=user_input,
            description=user_input,
            desired_end_state="Objective completed successfully",
            verification_criteria=[],
            constraints=[],
            required_capabilities=self._extract_capabilities(user_input),
            input_files=context.get("files", []) if context else [],
            context=context or {},
        )

        self.task_store.create_objective(objective)

        tasks = self.planner.create_plan(objective)
        for task in tasks:
            self.task_store.create_task(task)

        return objective

    def _extract_capabilities(self, user_input: str) -> list[str]:
        import re
        caps = []
        lower = user_input.lower()

        # Use word boundaries for more precise matching
        fs_keywords = ["file", "read", "write", "list", "directory", "folder", "create", "delete", "copy", "move"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in fs_keywords):
            caps.append("filesystem")

        cmd_keywords = ["run", "execute", "command", "build", "install", "compile"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in cmd_keywords):
            caps.append("command")

        coding_keywords = ["code", "program", "function", "class", "debug", "fix", "refactor"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in coding_keywords):
            caps.append("coding")

        vision_keywords = ["image", "picture", "screenshot", "visual", "diagram", "photo", "ocr"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in vision_keywords):
            caps.append("vision")

        audio_keywords = ["audio", "voice", "speech", "transcribe", "tts", "speak", "record"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in audio_keywords):
            caps.append("audio")

        web_keywords = ["search", "web", "internet", "research", "look up", "find online", "browse"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in web_keywords):
            caps.append("web")

        memory_keywords = ["remember", "memory", "recall", "store", "save"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in memory_keywords):
            caps.append("memory")

        document_keywords = ["document", "pdf", "docx", "xlsx", "pptx", "report"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in document_keywords):
            caps.append("documents")

        data_keywords = ["data", "analyze", "csv", "pandas", "statistics", "chart", "plot"]
        if any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in data_keywords):
            caps.append("data_analysis")

        return caps

    async def run_objective(self, objective_id: UUID) -> None:
        self._running = True

        while self._running:
            tasks = self.task_store.get_tasks_for_objective(objective_id)

            pending = [t for t in tasks if t.status in (TaskStatus.CREATED, TaskStatus.PLANNING)]
            for task in pending:
                task.status = TaskStatus.READY
                task.updated_at = datetime.now(UTC)
                self.task_store.update_task(task)

            ready_tasks = self.planner.get_next_ready_tasks(objective_id)
            executable = [t for t in ready_tasks if self.planner.can_execute_task(t, tasks)]

            if not executable:
                running = [t for t in tasks if t.status == TaskStatus.RUNNING]
                if not running:
                    completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
                    failed = [t for t in tasks if t.status == TaskStatus.FAILED]

                    if failed and not any(t.status in (TaskStatus.RUNNING, TaskStatus.READY) for t in tasks):
                        break

                    if len(completed) == len(tasks) and tasks:
                        break

                await asyncio.sleep(0.5)
                continue

            for task in executable:
                asyncio.create_task(self._execute_task(task))

            await asyncio.sleep(0.1)

    async def _execute_task(self, task: Task) -> None:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        task.attempts += 1
        task.updated_at = datetime.now(UTC)
        self.task_store.update_task(task)

        try:
            result = await execute_tool(task.tool_id, task, task.input_data, self.task_store)

            self.task_store.add_tool_result(result)
            task.output_data = result.output

            verification = await self.verifier.verify_task(task, result)
            task.verification_result = verification

            if result.success and verification["success"]:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(UTC)
            else:
                task.status = TaskStatus.FAILED
                task.error = result.error or "Verification failed"

                failure_type = self.recovery.classify_failure(task, result)
                if self.recovery.should_retry(task, failure_type):
                    task.status = TaskStatus.RECOVERING
                    recovery_task = self.recovery.create_recovery_task(task, failure_type)
                    self.task_store.create_task(recovery_task)

        except (RuntimeError, ValueError, OSError) as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)

        task.updated_at = datetime.now(UTC)
        self.task_store.update_task(task)

    def stop(self) -> None:
        self._running = False

    def get_status(self, objective_id: UUID) -> dict[str, Any]:
        tasks = self.task_store.get_tasks_for_objective(objective_id)
        return {
            "total": len(tasks),
            "completed": len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
            "failed": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            "running": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
            "ready": len([t for t in tasks if t.status == TaskStatus.READY]),
        }