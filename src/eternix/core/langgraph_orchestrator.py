import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from eternix.core.models import (
    CapabilityStatus,
    Objective,
    Task,
    TaskPriority,
    TaskStatus,
)
from eternix.core.task_store import TaskStore
from eternix.inference.llama_cpp import InferenceBackend, InferenceRequest
from eternix.models.manager import ModelManager
from eternix.tools.registry import execute_tool, tool_registry


class OrchestratorState(dict):
    objective_id: str
    objective: Objective
    tasks: list[Task]
    current_task_id: str | None
    status: str
    error: str | None
    retry_count: int
    max_retries: int
    verification_results: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    metadata: dict[str, Any]
    final_response: str


class IntelligentAgent:
    def __init__(self, task_store: TaskStore, model_manager: ModelManager):
        self.task_store = task_store
        self.model_manager = model_manager
        self.inference = InferenceBackend(task_store)

    async def reason_about_objective(self, objective: Objective) -> dict[str, Any]:
        prompt = f"""You are ETERNIX, an autonomous AI agent. Analyze this objective and create a detailed execution plan.

Objective: {objective.user_input}
Description: {objective.description}
Desired End State: {objective.desired_end_state}
Required Capabilities: {objective.required_capabilities}

Available Tools:
{self._get_available_tools_summary()}

Create a plan with specific steps, each step should specify:
1. What capability/tool to use
2. What the specific action is
3. What input data is needed
4. Expected output
5. Dependencies on other steps

Return as JSON with this structure:
{{
    "analysis": "Your analysis of the objective",
    "steps": [
        {{
            "step": 1,
            "capability": "capability_name",
            "tool": "tool_id",
            "description": "What this step does",
            "input_data": {{...}},
            "depends_on": [],
            "priority": "HIGH|NORMAL|LOW"
        }}
    ],
    "requires_approval": false,
    "estimated_duration": "time estimate"
}}"""

        role = await self.model_manager.get_model_for_task("reasoning")
        request = InferenceRequest(
            prompt=prompt,
            model="",
            max_tokens=2048,
            temperature=0.3,
            top_p=0.95,
        )
        response = await self.model_manager.run_inference(role, request)
        
        # Extract JSON from response (model may echo prompt)
        text = response.text.strip()
        # Find the first complete JSON object
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            text = text[first_brace:last_brace + 1]
        
        try:
            plan = json.loads(text)
            return plan
        except json.JSONDecodeError:
            return self._fallback_plan(objective)

    def _get_available_tools_summary(self) -> str:
        tools = tool_registry.list_tools()
        summary = []
        for tool in tools:
            summary.append(f"- {tool.id}: {tool.description} (tags: {', '.join(tool.tags)})")
        return "\n".join(summary)

    def _fallback_plan(self, objective: Objective) -> dict[str, Any]:
        """Deterministic intent router used when no reasoning model is available.

        Recognizable intents are mapped to real tools.  Conversational
        input produces an empty plan so the respond node answers the
        user directly instead of inventing a filesystem task.
        """
        import re

        user_input = objective.user_input.lower()

        def extract_filename() -> str | None:
            m = re.search(r"([\w\.-]+\.\w+)", user_input)
            return m.group(1) if m else None

        def extract_path() -> str:
            m = re.search(r"\bin\s+([^\s,;!?]+)", user_input)
            if m:
                candidate = m.group(1)
                if candidate.startswith(("/", "~", "./", "../")) or "/" in candidate or "." in candidate:
                    return candidate
            return "."

        def extract_query(marker: str) -> str:
            if marker in user_input:
                q = user_input[user_input.index(marker) + len(marker):].strip(" ?.")
                for prefix in ("the web for", "the web", "web for", "for", "web"):
                    if q.startswith(prefix + " "):
                        q = q[len(prefix) + 1:]
                if q:
                    return q
            return user_input

        steps: list[dict[str, Any]] = []

        # Image generation — checked before file writing so that
        # "create an image" generates instead of writing a file.
        if re.search(r"\b(image|picture|photo|illustration|painting|drawing)\b", user_input) and re.search(
            r"\b(generate|create|make|draw|paint)\b", user_input
        ):
            m = re.search(
                r"(?:image|picture|photo|illustration|painting|drawing)(?:\s+of\s+|\s+showing\s+|\s+with\s+)(.+?)(?:\?|\.|please|$)",
                user_input,
            )
            prompt = m.group(1).strip() if m else user_input
            steps.append({
                "step": 1,
                "capability": "generation",
                "tool": "gen.text_to_image",
                "description": f"Generate image: {prompt[:120]}",
                "input_data": {"prompt": prompt},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "Image generation requested", "steps": steps, "requires_approval": False, "estimated_duration": "30 seconds"}

        # Create a directory.
        if re.search(r"\b(create|make)\b", user_input) and re.search(r"\b(directory|folder)\b", user_input) and not extract_filename():
            steps.append({
                "step": 1,
                "capability": "filesystem",
                "tool": "fs.mkdir",
                "description": f"Create directory {extract_path()}",
                "input_data": {"path": extract_path()},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "Directory creation requested", "steps": steps, "requires_approval": False, "estimated_duration": "10 seconds"}

        # Write/create a file.
        if re.search(r"\b(create|write|make|build)\b", user_input) and (extract_filename() or re.search(r"\b(file|document|script)\b", user_input)):
            fname = extract_filename() or "output.txt"
            content = "# Generated file"
            if "python" in user_input or fname.endswith(".py"):
                content = "def hello():\n    print('Hello, World!')\n\nif __name__ == '__main__':\n    hello()\n"
            elif fname.endswith((".html", ".htm")):
                content = "<!DOCTYPE html>\n<html><body><h1>Hello</h1></body></html>\n"
            steps.append({
                "step": 1,
                "capability": "filesystem",
                "tool": "fs.write",
                "description": f"Write file {fname}",
                "input_data": {"path": fname, "content": content},
                "depends_on": [],
                "priority": "HIGH",
            })
            steps.append({
                "step": 2,
                "capability": "filesystem",
                "tool": "fs.read",
                "description": f"Verify {fname}",
                "input_data": {"path": fname},
                "depends_on": [1],
                "priority": "HIGH",
            })
            return {"analysis": "File write requested", "steps": steps, "requires_approval": False, "estimated_duration": "30 seconds"}

        # List files or directories.
        if re.search(r"\b(list|ls|show|browse)\b", user_input) and re.search(r"\b(files?|directories?|folders?|contents?)\b", user_input):
            listing_path = extract_path()
            description = "List files in current directory" if listing_path == "." else f"List files in {listing_path}"
            steps.append({
                "step": 1,
                "capability": "filesystem",
                "tool": "fs.list",
                "description": description,
                "input_data": {"path": listing_path},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "File listing requested", "steps": steps, "requires_approval": False, "estimated_duration": "10 seconds"}

        # Read a file.
        if re.search(r"\b(read|open|view)\b", user_input) and extract_filename():
            fname = extract_filename()
            steps.append({
                "step": 1,
                "capability": "filesystem",
                "tool": "fs.read",
                "description": f"Read file {fname}",
                "input_data": {"path": fname},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "File read requested", "steps": steps, "requires_approval": False, "estimated_duration": "10 seconds"}

        # Search within files.
        if re.search(r"\b(find|search)\b", user_input) and re.search(r"\b(file|files|content|code)\b", user_input):
            m = re.search(r"\b(?:find|search)(?:\s+for)?\s+(.+?)(?:\s+in\s+.+)?$", user_input)
            pattern = m.group(1).strip(" ?.") if m else user_input
            steps.append({
                "step": 1,
                "capability": "filesystem",
                "tool": "fs.search",
                "description": f"Search files for {pattern[:120]}",
                "input_data": {"pattern": pattern},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "File search requested", "steps": steps, "requires_approval": False, "estimated_duration": "20 seconds"}

        # Run a shell command.
        if re.search(r"\b(run|execute)\b", user_input) and re.search(r"\b(command|cmd|shell)?\b", user_input):
            m = re.search(r"\b(?:run|execute)(?:\s+(?:the\s+|a\s+))?(.+?)(?:\s+command)?$", user_input)
            command = m.group(1).strip(" ?.") if m else user_input
            steps.append({
                "step": 1,
                "capability": "command",
                "tool": "cmd.exec",
                "description": f"Run command: {command[:120]}",
                "input_data": {"command": command},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "Command execution requested", "steps": steps, "requires_approval": False, "estimated_duration": "30 seconds"}

        # Search the web.
        if re.search(r"\b(search|look up|google|web|internet|online|news|research)\b", user_input):
            query = extract_query("search") if "search" in user_input else extract_query("look up")
            steps.append({
                "step": 1,
                "capability": "web",
                "tool": "web.search",
                "description": f"Search the web: {query[:120]}",
                "input_data": {"query": query},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "Web search requested", "steps": steps, "requires_approval": False, "estimated_duration": "30 seconds"}

        # Compute a math expression.
        if re.search(r"\b(calculate|compute|solve|math)\b", user_input):
            m = re.search(r"\b(?:calculate|compute|solve)(?:\s+(?:the\s+))?(.+?)(?:\?|$)", user_input)
            expression = m.group(1).strip(" ?.") if m else user_input
            steps.append({
                "step": 1,
                "capability": "data_analysis",
                "tool": "data.sympy",
                "description": f"Compute: {expression[:120]}",
                "input_data": {"expression": expression},
                "depends_on": [],
                "priority": "HIGH",
            })
            return {"analysis": "Computation requested", "steps": steps, "requires_approval": False, "estimated_duration": "10 seconds"}

        # Conversational input — no tool tasks; the respond node
        # answers the user directly.
        return {"analysis": "conversational", "steps": [], "requires_approval": False, "estimated_duration": "0 seconds"}
        steps.append({
            "step": 1,
            "capability": "filesystem",
            "tool": "fs.list",
            "description": "List files in current directory",
            "input_data": {"path": "."},
            "depends_on": [],
            "priority": "HIGH",
        })
        return {"analysis": "Using fallback planning", "steps": steps, "requires_approval": False, "estimated_duration": "30 seconds"}


    async def select_tool_for_task(self, task: Task, available_tools: list[str]) -> str | None:
        tool_descriptions = []
        for tool_id in available_tools:
            tool = tool_registry.get(tool_id)
            if tool:
                tool_descriptions.append(f"- {tool.id}: {tool.description}")

        prompt = f"""Select the best tool for this task:

Task: {task.description}
Capability: {task.capability}
Available Tools:
{chr(10).join(tool_descriptions)}

Return only the tool ID that best matches this task, or "none" if no suitable tool exists."""

        role = await self.model_manager.get_model_for_task("reasoning")
        request = InferenceRequest(
            prompt=prompt,
            model="",
            max_tokens=100,
            temperature=0.1,
            top_p=0.95,
        )
        response = await self.model_manager.run_inference(role, request)
        
        selected = response.text.strip().lower()
        if selected in available_tools:
            return selected
        return None

    async def generate_task_input(self, task: Task, context: dict[str, Any]) -> dict[str, Any]:
        tool = tool_registry.get(task.tool_id)
        if not tool:
            return task.input_data

        prompt = f"""Generate input data for this tool:

Tool: {tool.id}
Tool Description: {tool.description}
Input Schema: {json.dumps(tool.input_schema, indent=2)}
Task: {task.description}
Task Input Data: {json.dumps(task.input_data, indent=2)}
Context: {json.dumps(context, indent=2)}

Return only valid JSON matching the input schema."""

        role = await self.model_manager.get_model_for_task("reasoning")
        request = InferenceRequest(
            prompt=prompt,
            model="",
            max_tokens=1024,
            temperature=0.3,
            top_p=0.95,
        )
        response = await self.model_manager.run_inference(role, request)
        
        # Extract JSON from response (model may echo prompt)
        text = response.text.strip()
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            text = text[first_brace:last_brace + 1]
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return task.input_data

    async def verify_result(self, task: Task, result: Any, objective: Objective) -> dict[str, Any]:
        prompt = f"""Verify if this task result satisfies the objective:

Objective: {objective.user_input}
Task: {task.description}
Tool Used: {task.tool_id}
Result: {json.dumps(result.output if hasattr(result, 'output') else str(result), indent=2)}

Verification Criteria:
{chr(10).join(objective.verification_criteria)}

Return JSON with:
{{
    "success": true/false,
    "checks": ["list of verification checks passed"],
    "issues": ["list of issues found"],
    "confidence": 0.0-1.0
}}"""

        role = await self.model_manager.get_model_for_task("reasoning")
        request = InferenceRequest(
            prompt=prompt,
            model="",
            max_tokens=512,
            temperature=0.1,
            top_p=0.95,
        )
        response = await self.model_manager.run_inference(role, request)
        
        # Extract JSON from response (model may echo prompt)
        text = response.text.strip()
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            text = text[first_brace:last_brace + 1]
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"success": result.success if hasattr(result, 'success') else False, "checks": [], "issues": ["Failed to parse verification"], "confidence": 0.5}


class LangGraphOrchestrator:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store
        self.model_manager = ModelManager(task_store)
        self.agent = IntelligentAgent(task_store, self.model_manager)
        self.inference = InferenceBackend(task_store)
        self._graph = None
        self._checkpointer = None

    async def initialize(self) -> None:
        await self.model_manager.initialize()
        # Register all tools
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
        await self._register_capabilities()
        # Graph is built per-run with MemorySaver
        self._graph = None

    async def _register_capabilities(self) -> None:
        from eternix.core.models import Capability, CapabilityStatus
        
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
        
        # Discover models and update capability statuses
        await self._discover_models()

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

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(OrchestratorState)

        graph.add_node("interpret", self._interpret_node)
        graph.add_node("plan", self._plan_node)
        graph.add_node("validate_plan", self._validate_plan_node)
        graph.add_node("select_tools", self._select_tools_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("inspect", self._inspect_node)
        graph.add_node("verify", self._verify_node)
        graph.add_node("recover", self._recover_node)
        graph.add_node("deliver", self._deliver_node)
        graph.add_node("approval_gate", self._approval_gate_node)

        graph.set_entry_point("interpret")

        graph.add_edge("interpret", "plan")
        graph.add_edge("plan", "validate_plan")
        graph.add_conditional_edges(
            "validate_plan",
            self._plan_validation_decision,
            {
                "valid": "select_tools",
                "invalid": "plan",
                "needs_approval": "approval_gate",
            },
        )
        graph.add_edge("approval_gate", "select_tools")
        graph.add_edge("select_tools", "execute")
        graph.add_edge("execute", "inspect")
        graph.add_conditional_edges(
            "inspect",
            self._inspection_decision,
            {
                "continue": "execute",
                "retry": "execute",
                "recover": "recover",
                "done": "verify",
            },
        )
        graph.add_edge("verify", "deliver")
        graph.add_conditional_edges(
            "recover",
            self._recovery_decision,
            {
                "retry": "execute",
                "replan": "plan",
                "fail": "deliver",
            },
        )
        graph.add_edge("deliver", END)

        return graph.compile(checkpointer=self._checkpointer)

    async def _interpret_node(self, state: OrchestratorState) -> OrchestratorState:
        objective = state["objective"]
        user_input = objective.user_input.lower()

        capabilities = []
        if any(kw in user_input for kw in ["file", "read", "write", "list", "create", "directory", "folder", "delete", "copy", "move"]):
            capabilities.append("filesystem")
        if any(kw in user_input for kw in ["run", "execute", "command", "build", "install", "compile"]):
            capabilities.append("command")
        if any(kw in user_input for kw in ["code", "program", "function", "class", "debug", "fix", "refactor"]):
            capabilities.append("coding")
        if any(kw in user_input for kw in ["search", "research", "find", "look up", "web", "internet", "browse"]):
            capabilities.append("web")
        if any(kw in user_input for kw in ["document", "pdf", "docx", "xlsx", "pptx", "report"]):
            capabilities.append("documents")
        if any(kw in user_input for kw in ["image", "picture", "visual", "diagram", "chart", "screenshot", "photo", "ocr"]):
            capabilities.append("vision")
        if any(kw in user_input for kw in ["audio", "voice", "speech", "transcribe", "tts", "speak", "record"]):
            capabilities.append("audio")
        if any(kw in user_input for kw in ["data", "analyze", "csv", "pandas", "statistics", "chart", "plot"]):
            capabilities.append("data_analysis")
        if any(kw in user_input for kw in ["remember", "memory", "recall", "store", "save"]):
            capabilities.append("memory")

        objective.required_capabilities = capabilities
        objective.verification_criteria = self._generate_verification_criteria(objective)
        self.task_store.update_objective(objective)

        state["objective"] = objective
        state["metadata"]["interpreted_capabilities"] = capabilities
        state["status"] = "interpreted"
        return state

    def _generate_verification_criteria(self, objective: Objective) -> list[str]:
        criteria = ["Task completed successfully"]
        user_input = objective.user_input.lower()
        if "write" in user_input or "create" in user_input:
            criteria.append("Output file exists and contains expected content")
        if "run" in user_input or "execute" in user_input:
            criteria.append("Command executed with exit code 0")
        if "search" in user_input or "research" in user_input:
            criteria.append("Sources cited with URLs")
        if "code" in user_input or "program" in user_input:
            criteria.append("Code is syntactically correct and follows best practices")
        if "image" in user_input or "visual" in user_input:
            criteria.append("Image generated or analyzed successfully")
        return criteria

    async def _plan_node(self, state: OrchestratorState) -> OrchestratorState:
        objective = state["objective"]
        
        plan = await self.agent.reason_about_objective(objective)
        
        tasks = []
        for step in plan.get("steps", []):
            capability = step.get("capability", "reasoning")
            tool = step.get("tool", "")
            input_data = step.get("input_data", {})
            
            # Normalize paths to relative paths
            if isinstance(input_data, dict):
                for key, value in input_data.items():
                    if isinstance(value, str) and value.startswith("/"):
                        # Convert absolute path to relative
                        input_data[key] = value.lstrip("/")
            
            # Validate tool exists in registry, fallback if not
            if (tool and not tool_registry.get(tool)) or not tool:
                available_tools = [t.id for t in tool_registry.list_tools() if capability in t.tags]
                if available_tools:
                    tool = available_tools[0]

            priority_map = {"HIGH": TaskPriority.HIGH, "NORMAL": TaskPriority.NORMAL, "LOW": TaskPriority.LOW}
            priority = priority_map.get(step.get("priority", "NORMAL"), TaskPriority.NORMAL)

            task = Task(
                id=uuid4(),
                objective_id=objective.id,
                description=step.get("description", f"Execute {tool}"),
                capability=capability,
                tool_id=tool if tool else None,
                input_data=input_data,
                priority=priority,
                max_attempts=3,
            )
            tasks.append(task)

        for task in tasks:
            self.task_store.create_task(task)

        state["tasks"] = tasks
        state["metadata"]["plan"] = plan
        state["metadata"]["requires_approval"] = plan.get("requires_approval", False)
        state["status"] = "planned"
        return state

    async def _validate_plan_node(self, state: OrchestratorState) -> OrchestratorState:
        tasks = state["tasks"]
        
        for task in tasks:
            if task.tool_id:
                tool = tool_registry.get(task.tool_id)
                if not tool:
                    state["status"] = "plan_invalid"
                    state["error"] = f"Tool {task.tool_id} not found"
                    return state

        high_risk = any(t.capability in ["command", "filesystem"] and
                       t.tool_id in ["fs.delete", "fs.move", "cmd.exec"]
                       for t in tasks)
        if high_risk or state["metadata"].get("requires_approval", False):
            state["status"] = "needs_approval"
            return state

        state["status"] = "plan_valid"
        return state

    def _plan_validation_decision(self, state: OrchestratorState) -> Literal["valid", "invalid", "needs_approval"]:
        status = state["status"]
        if status == "plan_valid":
            return "valid"
        elif status == "plan_invalid":
            return "invalid"
        elif status == "needs_approval":
            return "needs_approval"
        return "invalid"

    async def _approval_gate_node(self, state: OrchestratorState) -> OrchestratorState:
        state["metadata"]["awaiting_approval"] = True
        state["status"] = "awaiting_approval"
        return state

    async def _select_tools_node(self, state: OrchestratorState) -> OrchestratorState:
        tasks = state["tasks"]
        ready_tasks = [t for t in tasks if t.status == TaskStatus.CREATED]

        for task in ready_tasks:
            if task.tool_id:
                task.status = TaskStatus.READY
                task.updated_at = datetime.now(UTC)
                self.task_store.update_task(task)

        state["tasks"] = tasks
        state["status"] = "tools_selected"
        return state

    async def _execute_node(self, state: OrchestratorState) -> OrchestratorState:
        tasks = state["tasks"]
        # Include READY tasks and FAILED tasks that can be retried
        ready_tasks = [t for t in tasks if t.status == TaskStatus.READY]
        retriable_tasks = [t for t in tasks if t.status == TaskStatus.FAILED and t.attempts < t.max_attempts]
        all_executable = ready_tasks + retriable_tasks

        if not all_executable:
            state["status"] = "no_ready_tasks"
            return state

        # Prefer READY tasks, then retriable FAILED tasks
        task = all_executable[0]
        state["current_task_id"] = str(task.id)

        # If retrying a failed task, reset status to READY first
        if task.status == TaskStatus.FAILED:
            task.status = TaskStatus.READY
            self.task_store.update_task(task)

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        task.attempts += 1
        self.task_store.update_task(task)

        try:
            input_data = task.input_data
            if task.tool_id:
                input_data = await self.agent.generate_task_input(task, state["metadata"])
            
            result = await execute_tool(task.tool_id, task, input_data, self.task_store)
            self.task_store.add_tool_result(result)
            task.output_data = result.output

            # Update task status based on result
            if result.success:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now(UTC)
            else:
                task.status = TaskStatus.FAILED
                task.error = result.error
            self.task_store.update_task(task)

            state["tasks"] = tasks
            state["current_task_id"] = str(task.id)
            state["metadata"]["last_result"] = {
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "exit_code": result.exit_code,
            }
            state["status"] = "executed"
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            self.task_store.update_task(task)
            state["error"] = str(e)
            state["status"] = "execution_error"

        return state

    async def _inspect_node(self, state: OrchestratorState) -> OrchestratorState:
        tasks = state["tasks"]
        current_task_id = state["current_task_id"]

        if not current_task_id:
            state["status"] = "no_current_task"
            return state

        task = next((t for t in tasks if str(t.id) == current_task_id), None)
        if not task:
            state["status"] = "task_not_found"
            return state

        last_result = state["metadata"].get("last_result", {})
        if last_result.get("success"):
            state["status"] = "inspection_passed"
        else:
            if task.attempts >= task.max_attempts:
                state["status"] = "max_retries_exceeded"
            else:
                state["status"] = "inspection_failed"

        return state

    def _inspection_decision(self, state: OrchestratorState) -> Literal["continue", "retry", "recover", "done"]:
        status = state["status"]
        if status == "inspection_passed":
            tasks = state["tasks"]
            remaining = [t for t in tasks if t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED)]
            if not remaining:
                return "done"
            return "continue"
        elif status == "inspection_failed":
            return "retry"
        elif status == "max_retries_exceeded":
            return "recover"
        return "recover"

    async def _verify_node(self, state: OrchestratorState) -> OrchestratorState:
        tasks = state["tasks"]
        current_task_id = state["current_task_id"]

        if not current_task_id:
            return state

        task = next((t for t in tasks if str(t.id) == current_task_id), None)
        if not task:
            return state

        last_result = state["metadata"].get("last_result", {})
        result_obj = type('obj', (object,), last_result)
        
        verification = await self.agent.verify_result(task, result_obj, state["objective"])
        
        state["verification_results"].append(verification)
        task.verification_result = verification

        if verification.get("success", False):
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC)
        else:
            task.status = TaskStatus.FAILED
            task.error = "Verification failed: " + ", ".join(verification.get("issues", []))

        self.task_store.update_task(task)
        state["tasks"] = tasks
        state["status"] = "verified"
        return state

    async def _recover_node(self, state: OrchestratorState) -> OrchestratorState:
        tasks = state["tasks"]
        current_task_id = state["current_task_id"]

        if not current_task_id:
            state["status"] = "recovery_fail"
            return state

        task = next((t for t in tasks if str(t.id) == current_task_id), None)
        if not task:
            state["status"] = "recovery_fail"
            return state

        last_result = state["metadata"].get("last_result", {})
        failure_type = self._classify_failure(last_result)

        if failure_type == "timeout" and task.attempts < task.max_attempts:
            task.input_data["timeout"] = task.input_data.get("timeout", 60) * 2
            task.status = TaskStatus.READY
            self.task_store.update_task(task)
            state["status"] = "recovery_retry"
        elif failure_type == "permission":
            state["status"] = "recovery_fail"
            task.status = TaskStatus.FAILED
            task.error = "Permission denied - cannot recover"
            self.task_store.update_task(task)
        else:
            recovery_task = Task(
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
            self.task_store.create_task(recovery_task)
            state["tasks"].append(recovery_task)
            state["status"] = "recovery_replan"

        return state

    def _classify_failure(self, result: dict) -> str:
        error = result.get("error", "").lower()
        if "timeout" in error:
            return "timeout"
        if "permission" in error:
            return "permission"
        if "not found" in error:
            return "not_found"
        if result.get("exit_code") and result["exit_code"] != 0:
            return "non_zero_exit"
        return "unknown"

    def _recovery_decision(self, state: OrchestratorState) -> Literal["retry", "replan", "fail"]:
        return state["status"].replace("recovery_", "")

    async def _deliver_node(self, state: OrchestratorState) -> OrchestratorState:
        tasks = state["tasks"]

        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in tasks if t.status == TaskStatus.FAILED]

        artifacts = []
        for task in completed:
            if task.output_data:
                artifacts.append({
                    "task_id": str(task.id),
                    "type": "tool_output",
                    "data": task.output_data,
                })

        state["artifacts"] = artifacts
        state["metadata"]["completed_tasks"] = len(completed)
        state["metadata"]["failed_tasks"] = len(failed)
        state["metadata"]["total_tasks"] = len(tasks)
        state["status"] = "delivered"
        return state

    async def _respond_node(self, state: OrchestratorState) -> OrchestratorState:
        """Generate a natural language response summarizing the execution results."""
        objective = state["objective"]
        tasks = state["tasks"]

        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in tasks if t.status == TaskStatus.FAILED]

        # Build a summary of what was done
        task_summaries = []
        for task in completed:
            tool_info = f" (using {task.tool_id})" if task.tool_id else ""
            output_summary = ""
            if task.output_data and isinstance(task.output_data, dict):
                if task.output_data.get("stdout"):
                    output_summary = f" - Output: {str(task.output_data['stdout'])[:200]}"
                elif "result" in task.output_data:
                    output_summary = f" - Result: {str(task.output_data['result'])[:200]}"
                elif "content" in task.output_data:
                    output_summary = f" - Content: {str(task.output_data['content'])[:200]}"
            task_summaries.append(f"- {task.description}{tool_info}{output_summary}")

        for task in failed:
            task_summaries.append(f"- {task.description} (FAILED: {task.error or 'Unknown error'})")

        prompt = f"""You are ETERNIX, an autonomous AI agent. Generate a clear, helpful response for the user based on the completed objective.

Original Request: {objective.user_input}

Tasks Completed: {len(completed)}
Tasks Failed: {len(failed)}

Task Details:
{chr(10).join(task_summaries) if task_summaries else "No tasks executed."}

Generate a natural, conversational response that:
1. Summarizes what was accomplished
2. Highlights key results or findings
3. Mentions any failures and what they mean
4. Provides any relevant outputs or next steps
5. Is concise but informative

Do not mention internal process details like "task execution" or "orchestrator" - speak directly to the user."""

        final_response = ""
        try:
            role = await self.model_manager.get_model_for_task("reasoning")
            request = InferenceRequest(
                prompt=prompt,
                model="",
                max_tokens=1024,
                temperature=0.5,
                top_p=0.95,
            )
            response = await self.model_manager.run_inference(role, request)
            if response.finish_reason == "stop" and response.text.strip():
                final_response = response.text.strip()
        except Exception:
            pass
        
        # Fallback response if inference fails or returns empty
        if not final_response:
            if completed:
                parts = [f"Completed {len(completed)} task(s)."]
                if failed:
                    parts.append(f"{len(failed)} task(s) failed.")
                if task_summaries:
                    parts.append("Summary:")
                    parts.extend(task_summaries[:5])  # Limit to first 5
                    if len(task_summaries) > 5:
                        parts.append(f"... and {len(task_summaries) - 5} more")
                final_response = " ".join(parts)
            elif not failed and not (state["metadata"].get("plan") or {}).get("steps"):
                # Conversational objective: the plan deliberately
                # contained no tool tasks, so answer directly.
                final_response = self._conversational_response(objective.user_input)
            else:
                final_response = "Objective executed but no tasks completed successfully."
        
        state["final_response"] = final_response
        state["status"] = "responded"
        return state

    @staticmethod
    def _conversational_response(user_input: str) -> str:
        """Direct answer for conversational input when no reasoning model is loaded."""
        import re

        text = user_input.lower().strip()
        if re.search(r"\b(hello|hi|hey|good morning|good afternoon|good evening|how are you|what's up)\b", text):
            return (
                "Hello! I'm Eternix, your autonomous agent. I plan and execute real "
                "tasks end to end — listing, reading and writing files, running commands, "
                "searching the web, and generating images. What would you like me to do?"
            )
        if re.search(r"\b(who are you|what are you|your name|what can you do)\b", text):
            return (
                "I'm Eternix, an autonomous agent. I choose the capabilities and tools "
                "each objective needs and carry it out myself. Ask me to list files in a "
                "folder, read or write a document, run a command, search the web, or "
                "generate an image."
            )
        if re.search(r"\b(thank|thanks|appreciated)\b", text):
            return "You're welcome. What else can I do for you?"
        return (
            "I don't have a reasoning model loaded, so I can't answer open-ended "
            "questions yet. I can still run real tasks with my built-in tools: list, "
            "read, write, move and delete files; run shell commands; search the web; "
            "generate images (when a cloud provider key is configured); analyze data; "
            "and compute expressions. Try something concrete, like: "
            "\"list the files in the current directory\"."
        )

    async def run_objective(self, objective_id: UUID) -> dict[str, Any]:
        objective = self.task_store.get_objective(objective_id)
        if not objective:
            raise ValueError(f"Objective {objective_id} not found")

        tasks = self.task_store.get_tasks_for_objective(objective_id)

        initial_state: OrchestratorState = {
            "objective_id": str(objective_id),
            "objective": objective,
            "tasks": tasks,
            "current_task_id": None,
            "status": "started",
            "error": None,
            "retry_count": 0,
            "max_retries": 3,
            "verification_results": [],
            "artifacts": [],
            "metadata": {},
            "final_response": "",
        }

        # Use MemorySaver for reliable execution (SQLite checkpointer times out)
        checkpointer = MemorySaver()

        # Build graph with this checkpointer
        graph = self._build_graph_with_checkpointer(checkpointer)

        config = {"configurable": {"thread_id": str(objective_id)}}
        final_state = await graph.ainvoke(initial_state, config=config)
        
        # Extract final response from state
        final_response = final_state.get("final_response", "")
        
        return {
            "final_response": final_response,
            "status": final_state.get("status", "completed"),
        }

    async def resume_objective(self, objective_id: UUID) -> None:
        objective = self.task_store.get_objective(objective_id)
        if not objective:
            raise ValueError(f"Objective {objective_id} not found")

        # Use MemorySaver for reliable execution (SQLite checkpointer times out)
        checkpointer = MemorySaver()

        # Build graph with this checkpointer
        graph = self._build_graph_with_checkpointer(checkpointer)

        config = {"configurable": {"thread_id": str(objective_id)}}
        state = await graph.aget_state(config)
        if state:
            await graph.ainvoke(None, config=config)

    async def cancel_objective(self, objective_id: UUID) -> None:
        tasks = self.task_store.get_tasks_for_objective(objective_id)
        for task in tasks:
            if task.status in (TaskStatus.RUNNING, TaskStatus.READY):
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now(UTC)
                self.task_store.update_task(task)

    def get_status(self, objective_id: UUID) -> dict[str, Any]:
        tasks = self.task_store.get_tasks_for_objective(objective_id)
        return {
            "total": len(tasks),
            "completed": len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
            "failed": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            "running": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
            "ready": len([t for t in tasks if t.status == TaskStatus.READY]),
            "cancelled": len([t for t in tasks if t.status == TaskStatus.CANCELLED]),
        }

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

        return objective

    def _build_graph_with_checkpointer(self, checkpointer) -> StateGraph:
        graph = StateGraph(OrchestratorState)

        graph.add_node("interpret", self._interpret_node)
        graph.add_node("plan", self._plan_node)
        graph.add_node("validate_plan", self._validate_plan_node)
        graph.add_node("select_tools", self._select_tools_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("inspect", self._inspect_node)
        graph.add_node("verify", self._verify_node)
        graph.add_node("recover", self._recover_node)
        graph.add_node("deliver", self._deliver_node)
        graph.add_node("respond", self._respond_node)
        graph.add_node("approval_gate", self._approval_gate_node)

        graph.set_entry_point("interpret")

        graph.add_edge("interpret", "plan")
        graph.add_edge("plan", "validate_plan")
        graph.add_conditional_edges(
            "validate_plan",
            self._plan_validation_decision,
            {
                "valid": "select_tools",
                "invalid": "plan",
                "needs_approval": "approval_gate",
            },
        )
        graph.add_edge("approval_gate", "select_tools")
        graph.add_edge("select_tools", "execute")
        graph.add_edge("execute", "inspect")
        graph.add_conditional_edges(
            "inspect",
            self._inspection_decision,
            {
                "continue": "execute",
                "retry": "execute",
                "recover": "recover",
                "done": "verify",
            },
        )
        graph.add_edge("verify", "deliver")
        graph.add_edge("deliver", "respond")
        graph.add_conditional_edges(
            "recover",
            self._recovery_decision,
            {
                "retry": "execute",
                "replan": "plan",
                "fail": "deliver",
            },
        )
        graph.add_edge("respond", END)

        return graph.compile(checkpointer=checkpointer)

    def _extract_capabilities(self, user_input: str) -> list[str]:
        import re
        caps = []
        lower = user_input.lower()

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

    async def shutdown(self) -> None:
        await self.model_manager.shutdown()