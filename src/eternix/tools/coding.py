import asyncio
import json
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser

from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.filesystem import WorkspaceEscape, _resolve_path
from eternix.tools.registry import tool_registry


def get_parser_for_language(language: str) -> Parser | None:
    language_mapping = {
        "python": "tree_sitter_python",
        "javascript": "tree_sitter_javascript",
        "typescript": "tree_sitter_typescript",
        "java": "tree_sitter_java",
        "cpp": "tree_sitter_cpp",
        "rust": "tree_sitter_rust",
        "go": "tree_sitter_go",
        "c_sharp": "tree_sitter_c_sharp",
        "php": "tree_sitter_php",
        "dart": "tree_sitter_dart",
        "kotlin": "tree_sitter_kotlin",
        "sql": "tree_sitter_sql",
        "html": "tree_sitter_html",
        "css": "tree_sitter_css",
    }

    module_name = language_mapping.get(language.lower())
    if not module_name:
        return None

    try:
        module = __import__(module_name, fromlist=["language"])
        lang = Language(module.language())
        parser = Parser(lang)
        return parser
    except (ImportError, AttributeError):
        return None


async def coding_parse_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    code = input_data.get("code", "")
    language = input_data.get("language", "python")
    file_path = input_data.get("file_path", "")

    if not code and file_path:
        try:
            code = Path(file_path).read_text(encoding="utf-8")
        except OSError as e:
            return ToolResult(
                tool_id="coding.parse",
                task_id=task.id,
                success=False,
                error=f"Failed to read file: {e}",
            )

    if not code:
        return ToolResult(
            tool_id="coding.parse",
            task_id=task.id,
            success=False,
            error="No code or file path provided",
        )

    parser = get_parser_for_language(language)
    if not parser:
        return ToolResult(
            tool_id="coding.parse",
            task_id=task.id,
            success=False,
            error=f"Parser not available for language: {language}",
        )

    try:
        tree = parser.parse(code.encode("utf-8"))

        def extract_node(node, depth=0):
            if depth > 10:
                return {"type": node.type, "truncated": True}
            return {
                "type": node.type,
                "start": node.start_point,
                "end": node.end_point,
                "text": code[node.start_byte:node.end_byte] if node.end_byte - node.start_byte < 500 else "...",
                "children": [extract_node(child, depth + 1) for child in node.children],
            }

        ast = extract_node(tree.root_node)
        return ToolResult(
            tool_id="coding.parse",
            task_id=task.id,
            success=True,
            output={"language": language, "ast": ast},
        )
    except Exception as e:
        return ToolResult(
            tool_id="coding.parse",
            task_id=task.id,
            success=False,
            error=f"Parse failed: {e}",
        )


async def coding_search_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    query = input_data.get("query", "")
    path = input_data.get("path", ".")
    language = input_data.get("language", "")
    pattern = input_data.get("pattern", "")

    if not query and not pattern:
        return ToolResult(
            tool_id="coding.search",
            task_id=task.id,
            success=False,
            error="No query or pattern provided",
        )

    try:
        search_path = str(_resolve_path(path, task, task_store))
    except WorkspaceEscape as e:
        return ToolResult(tool_id="coding.search", task_id=task.id, success=False, error=str(e))

    try:
        cmd = ["rg", "--json"]
        if language:
            cmd.extend(["-t", language])
        if pattern:
            cmd.extend(["-g", pattern])
        cmd.append(query)
        cmd.append(search_path)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        results = []
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            if line.strip():
                try:
                    data = json.loads(line)
                    if data.get("type") == "match":
                        match_data = data.get("data", {})
                        results.append({
                            "file": match_data.get("path", {}).get("text", ""),
                            "line_number": match_data.get("line_number"),
                            "line": match_data.get("lines", {}).get("text", ""),
                            "match": match_data.get("submatches", []),
                        })
                except json.JSONDecodeError:
                    pass

        return ToolResult(
            tool_id="coding.search",
            task_id=task.id,
            success=True,
            output={"query": query, "results": results[:100]},
        )
    except Exception as e:
        return ToolResult(
            tool_id="coding.search",
            task_id=task.id,
            success=False,
            error=f"Search failed: {e}",
        )


async def coding_edit_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    file_path = input_data.get("file_path", "")
    operations = input_data.get("operations", [])

    if not file_path:
        return ToolResult(
            tool_id="coding.edit",
            task_id=task.id,
            success=False,
            error="No file path provided",
        )

    if not operations:
        return ToolResult(
            tool_id="coding.edit",
            task_id=task.id,
            success=False,
            error="No operations provided",
        )

    try:
        try:
            path = _resolve_path(file_path, task, task_store)
        except WorkspaceEscape as e:
            return ToolResult(tool_id="coding.edit", task_id=task.id, success=False, error=str(e))
        if not path.exists():
            return ToolResult(
                tool_id="coding.edit",
                task_id=task.id,
                success=False,
                error=f"File not found: {file_path}",
            )

        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

        for op in operations:
            op_type = op.get("type")
            if op_type == "replace":
                start = op.get("start_line", 1) - 1
                end = op.get("end_line", start + 1)
                new_content = op.get("content", "")
                if 0 <= start < len(lines):
                    lines[start:end] = [new_content + "\n" if not new_content.endswith("\n") else new_content]
            elif op_type == "insert":
                line = op.get("line", 1) - 1
                new_content = op.get("content", "")
                if 0 <= line <= len(lines):
                    lines.insert(line, new_content + "\n" if not new_content.endswith("\n") else new_content)
            elif op_type == "delete":
                start = op.get("start_line", 1) - 1
                end = op.get("end_line", start + 1)
                if 0 <= start < len(lines):
                    del lines[start:end]

        path.write_text("".join(lines), encoding="utf-8")

        return ToolResult(
            tool_id="coding.edit",
            task_id=task.id,
            success=True,
            output={"file_path": file_path, "operations_applied": len(operations)},
        )
    except Exception as e:
        return ToolResult(
            tool_id="coding.edit",
            task_id=task.id,
            success=False,
            error=f"Edit failed: {e}",
        )


async def coding_lint_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    file_path = input_data.get("file_path", "")
    path = input_data.get("path", ".")
    fix = input_data.get("fix", False)

    try:
        if file_path:
            targets = [str(_resolve_path(file_path, task, task_store))]
        else:
            targets = [str(_resolve_path(path, task, task_store))]
    except WorkspaceEscape as e:
        return ToolResult(tool_id="coding.lint", task_id=task.id, success=False, error=str(e))

    try:
        results = {}
        for target in targets:
            cmd = ["ruff", "check"]
            if fix:
                cmd.append("--fix")
            cmd.append(target)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            results[target] = {
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stdout.decode("utf-8", errors="replace"),
            }

        return ToolResult(
            tool_id="coding.lint",
            task_id=task.id,
            success=True,
            output={"results": results},
        )
    except Exception as e:
        return ToolResult(
            tool_id="coding.lint",
            task_id=task.id,
            success=False,
            error=f"Lint failed: {e}",
        )


async def coding_test_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = input_data.get("path", ".")
    test_file = input_data.get("test_file", "")
    args = input_data.get("args", [])

    try:
        resolved_path = _resolve_path(path, task, task_store)
    except WorkspaceEscape as e:
        return ToolResult(tool_id="coding.test", task_id=task.id, success=False, error=str(e))

    try:
        cmd = ["pytest", "-v"]
        if test_file:
            cmd.append(str(_resolve_path(test_file, task, task_store)))
        else:
            cmd.append(str(resolved_path))
        cmd.extend(args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(resolved_path) if resolved_path.is_dir() else str(resolved_path.parent),
        )
        stdout, stderr = await proc.communicate()

        return ToolResult(
            tool_id="coding.test",
            task_id=task.id,
            success=proc.returncode == 0,
            output={
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            },
        )
    except Exception as e:
        return ToolResult(
            tool_id="coding.test",
            task_id=task.id,
            success=False,
            error=f"Test failed: {e}",
        )


async def coding_git_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    repo_path = input_data.get("repo_path", ".")
    operation = input_data.get("operation", "status")
    args = input_data.get("args", [])

    try:
        resolved_repo = str(_resolve_path(repo_path, task, task_store))
    except WorkspaceEscape as e:
        return ToolResult(tool_id="coding.git", task_id=task.id, success=False, error=str(e))

    try:
        cmd = ["git", "-C", resolved_repo, operation]
        cmd.extend(args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        return ToolResult(
            tool_id="coding.git",
            task_id=task.id,
            success=proc.returncode == 0,
            output={
                "operation": operation,
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            },
        )
    except Exception as e:
        return ToolResult(
            tool_id="coding.git",
            task_id=task.id,
            success=False,
            error=f"Git operation failed: {e}",
        )


def register_coding_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="coding.parse",
            name="Parse Code",
            description="Parse source code into AST using tree-sitter",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "language": {"type": "string", "default": "python"},
                    "file_path": {"type": "string"},
                },
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["coding", "parse", "ast"],
        ),
        coding_parse_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="coding.search",
            name="Search Code",
            description="Search code using ripgrep",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "language": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "required": ["query"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["coding", "search", "ripgrep"],
        ),
        coding_search_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="coding.edit",
            name="Edit Code",
            description="Apply structured edits to source files",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["replace", "insert", "delete"]},
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                                "line": {"type": "integer"},
                                "content": {"type": "string"},
                            },
                            "required": ["type"],
                        },
                    },
                },
                "required": ["file_path", "operations"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["coding", "edit", "write"],
        ),
        coding_edit_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="coding.lint",
            name="Lint Code",
            description="Lint code using ruff",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "fix": {"type": "boolean", "default": False},
                },
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=60,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["coding", "lint", "ruff"],
        ),
        coding_lint_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="coding.test",
            name="Run Tests",
            description="Run tests using pytest",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "test_file": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=120,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["coding", "test", "pytest"],
        ),
        coding_test_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="coding.git",
            name="Git Operations",
            description="Perform git operations",
            input_schema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "default": "."},
                    "operation": {"type": "string", "enum": ["status", "diff", "log", "add", "commit", "push", "pull", "branch", "checkout"]},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["operation"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["coding", "git", "version_control"],
        ),
        coding_git_handler,
    )