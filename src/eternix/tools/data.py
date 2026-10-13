import json
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from eternix.core.config import settings
from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.registry import tool_registry


async def data_analyze_csv_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    path = input_data.get("path", "")
    operations = input_data.get("operations", [])

    if not path or not os.path.exists(path):
        return ToolResult(
            tool_id="data.analyze_csv",
            task_id=task.id,
            success=False,
            error="CSV file not found",
        )

    try:
        df = pd.read_csv(path)
        results = {"shape": df.shape, "columns": df.columns.tolist(), "dtypes": df.dtypes.astype(str).to_dict()}

        for op in operations:
            op_type = op.get("type")
            if op_type == "describe":
                results["describe"] = df.describe(include="all").to_dict()
            elif op_type == "head":
                n = op.get("n", 5)
                results["head"] = df.head(n).to_dict()
            elif op_type == "tail":
                n = op.get("n", 5)
                results["tail"] = df.tail(n).to_dict()
            elif op_type == "groupby":
                by = op.get("by")
                agg = op.get("agg", "mean")
                if by and by in df.columns:
                    results[f"groupby_{by}"] = df.groupby(by).agg(agg).to_dict()
            elif op_type == "filter":
                col = op.get("column")
                val = op.get("value")
                if col and col in df.columns:
                    results[f"filter_{col}_{val}"] = df[df[col] == val].to_dict()
            elif op_type == "correlation":
                results["correlation"] = df.select_dtypes(include=[np.number]).corr().to_dict()

        return ToolResult(
            tool_id="data.analyze_csv",
            task_id=task.id,
            success=True,
            output=results,
        )
    except Exception as e:
        return ToolResult(
            tool_id="data.analyze_csv",
            task_id=task.id,
            success=False,
            error=f"CSV analysis failed: {e}",
        )


async def data_analyze_python_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    code = input_data.get("code", "")
    datasets = input_data.get("datasets", {})

    if not code:
        return ToolResult(
            tool_id="data.analyze_python",
            task_id=task.id,
            success=False,
            error="No code provided",
        )

    try:
        namespace = {"np": np, "pd": pd, "datetime": datetime, "json": json}
        for name, data in datasets.items():
            if isinstance(data, list):
                namespace[name] = pd.DataFrame(data)
            elif isinstance(data, dict):
                namespace[name] = data

        exec(code, namespace)

        output_vars = {k: v for k, v in namespace.items() if not k.startswith("_") and k not in ["np", "pd", "datetime", "json"]}
        serializable = {}
        for k, v in output_vars.items():
            if isinstance(v, (pd.DataFrame, pd.Series)):
                serializable[k] = v.to_dict()
            elif isinstance(v, (np.ndarray, np.generic)):
                serializable[k] = v.tolist()
            elif isinstance(v, (str, int, float, bool, list, dict)) or v is None:
                serializable[k] = v
            else:
                serializable[k] = str(v)

        return ToolResult(
            tool_id="data.analyze_python",
            task_id=task.id,
            success=True,
            output=serializable,
        )
    except Exception as e:
        return ToolResult(
            tool_id="data.analyze_python",
            task_id=task.id,
            success=False,
            error=f"Python analysis failed: {e}",
        )


async def data_chart_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    chart_type = input_data.get("chart_type", "line")
    data = input_data.get("data", {})
    x = input_data.get("x", "")
    y = input_data.get("y", "")
    title = input_data.get("title", "Chart")
    output_path = input_data.get("output_path", "")

    if not output_path:
        output_path = f"/tmp/chart_{uuid4().hex[:8]}.png"

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        df = pd.DataFrame(data) if data else pd.DataFrame()

        plt.figure(figsize=(10, 6))
        plt.title(title)

        if chart_type == "line" and x and y:
            plt.plot(df[x], df[y])
            plt.xlabel(x)
            plt.ylabel(y)
        elif chart_type == "bar" and x and y:
            plt.bar(df[x], df[y])
            plt.xlabel(x)
            plt.ylabel(y)
        elif chart_type == "scatter" and x and y:
            plt.scatter(df[x], df[y])
            plt.xlabel(x)
            plt.ylabel(y)
        elif chart_type == "histogram" and x:
            plt.hist(df[x], bins=30)
            plt.xlabel(x)
            plt.ylabel("Frequency")
        elif chart_type == "pie" and x and y:
            plt.pie(df[y], labels=df[x], autopct="%1.1f%%")

        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()

        return ToolResult(
            tool_id="data.chart",
            task_id=task.id,
            success=True,
            output={"output_path": output_path, "size": os.path.getsize(output_path)},
        )
    except Exception as e:
        return ToolResult(
            tool_id="data.chart",
            task_id=task.id,
            success=False,
            error=f"Chart generation failed: {e}",
        )


async def data_sql_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    query = input_data.get("query", "")
    db_path = input_data.get("db_path", "")

    if not query:
        return ToolResult(
            tool_id="data.sql",
            task_id=task.id,
            success=False,
            error="No query provided",
        )

    if not db_path:
        db_path = str(settings.data_dir / "eternix.db")

    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)

        if query.strip().upper().startswith("SELECT"):
            rows = cursor.fetchall()
            results = [dict(row) for row in rows]
        else:
            conn.commit()
            results = {"affected_rows": cursor.rowcount}

        conn.close()

        return ToolResult(
            tool_id="data.sql",
            task_id=task.id,
            success=True,
            output=results,
        )
    except Exception as e:
        return ToolResult(
            tool_id="data.sql",
            task_id=task.id,
            success=False,
            error=f"SQL execution failed: {e}",
        )


async def data_sympy_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    expression = input_data.get("expression", "")
    operation = input_data.get("operation", "evaluate")

    if not expression:
        return ToolResult(
            tool_id="data.sympy",
            task_id=task.id,
            success=False,
            error="No expression provided",
        )

    try:
        import sympy as sp

        _x, _y, _z = sp.symbols("x y z")
        expr = sp.sympify(expression)

        if operation == "evaluate":
            result = expr.evalf()
        elif operation == "simplify":
            result = sp.simplify(expr)
        elif operation == "expand":
            result = sp.expand(expr)
        elif operation == "factor":
            result = sp.factor(expr)
        elif operation == "derivative":
            var = input_data.get("variable", "x")
            result = sp.diff(expr, sp.symbols(var))
        elif operation == "integrate":
            var = input_data.get("variable", "x")
            result = sp.integrate(expr, sp.symbols(var))
        elif operation == "solve":
            result = sp.solve(expr, sp.symbols(input_data.get("variable", "x")))
        else:
            result = expr

        return ToolResult(
            tool_id="data.sympy",
            task_id=task.id,
            success=True,
            output={"expression": str(expr), "result": str(result), "operation": operation},
        )
    except Exception as e:
        return ToolResult(
            tool_id="data.sympy",
            task_id=task.id,
            success=False,
            error=f"SymPy computation failed: {e}",
        )


def register_data_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="data.analyze_csv",
            name="Analyze CSV",
            description="Analyze CSV data with various operations",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["describe", "head", "tail", "groupby", "filter", "correlation"]},
                                "by": {"type": "string"},
                                "agg": {"type": "string"},
                                "column": {"type": "string"},
                                "value": {"type": "string"},
                                "n": {"type": "integer"},
                            },
                        },
                    },
                },
                "required": ["path"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=60,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["data", "csv", "analysis"],
        ),
        data_analyze_csv_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="data.analyze_python",
            name="Analyze with Python",
            description="Run Python data analysis code with pandas and numpy",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "datasets": {"type": "object"},
                },
                "required": ["code"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=120,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["data", "python", "analysis"],
        ),
        data_analyze_python_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="data.chart",
            name="Generate Chart",
            description="Generate charts and plots using matplotlib",
            input_schema={
                "type": "object",
                "properties": {
                    "chart_type": {"type": "string", "enum": ["line", "bar", "scatter", "histogram", "pie"]},
                    "data": {"type": "object"},
                    "x": {"type": "string"},
                    "y": {"type": "string"},
                    "title": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["chart_type"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=60,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["data", "chart", "visualization"],
        ),
        data_chart_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="data.sql",
            name="Execute SQL",
            description="Execute SQL queries on SQLite database",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "db_path": {"type": "string"}}, "required": ["query"]},
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["data", "sql", "database"],
        ),
        data_sql_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="data.sympy",
            name="SymPy Compute",
            description="Perform symbolic mathematics with SymPy",
            input_schema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "operation": {"type": "string", "enum": ["evaluate", "simplify", "expand", "factor", "derivative", "integrate", "solve"]},
                    "variable": {"type": "string"},
                },
                "required": ["expression"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["data", "sympy", "math"],
        ),
        data_sympy_handler,
    )