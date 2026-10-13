"""Image generation tools.

Local image generation is not available in this build: there is no
stable-diffusion-compatible runtime, no pipeline weights, and no GPU.
Every tool in this module therefore reports an honest, structured
"not available" result instead of fabricating output.  When a cloud
provider is configured (OPENAI_API_KEY / Stability key) the cloud
path becomes available; otherwise the capability is reported as
blocked by a missing dependency or credential.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from eternix.core.models import (
    Task,
    ToolDefinition,
    ToolResult,
    ToolSideEffect,
)
from eternix.core.task_store import TaskStore
from eternix.tools.registry import tool_registry


def _cloud_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("STABILITY_API_KEY"))


async def gen_text_to_image_handler(
    input_data: dict[str, Any], task: Task, task_store: TaskStore
) -> ToolResult:
    prompt = input_data.get("prompt", "")
    if not prompt:
        return ToolResult(
            tool_id="gen.text_to_image",
            task_id=task.id,
            success=False,
            error="No prompt provided",
        )

    if not _cloud_available():
        return ToolResult(
            tool_id="gen.text_to_image",
            task_id=task.id,
            success=False,
            error=(
                "Image generation is not available: no local image-generation "
                "pipeline is bundled and no cloud provider key is configured. "
                "Set OPENAI_API_KEY or STABILITY_API_KEY to enable cloud generation."
            ),
        )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024"},
            )
            if resp.status_code != 200:
                return ToolResult(
                    tool_id="gen.text_to_image",
                    task_id=task.id,
                    success=False,
                    error=f"Provider error {resp.status_code}: {resp.text[:200]}",
                )
            data = resp.json()
            url = data["data"][0]["url"]
            img = await client.get(url)
            out_path = Path(input_data.get("output_path", "/tmp/eternix_gen.png"))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(img.content)
            return ToolResult(
                tool_id="gen.text_to_image",
                task_id=task.id,
                success=True,
                output={"output_path": str(out_path), "size": out_path.stat().st_size, "url": url},
            )
    except Exception as e:
        return ToolResult(
            tool_id="gen.text_to_image",
            task_id=task.id,
            success=False,
            error=f"Image generation failed: {e}",
        )


async def gen_status_handler(
    input_data: dict[str, Any], task: Task, task_store: TaskStore
) -> ToolResult:
    return ToolResult(
        tool_id="gen.status",
        task_id=task.id,
        success=True,
        output={
            "local_generation": False,
            "local_reason": "No stable-diffusion-compatible runtime or weights bundled",
            "cloud_generation": _cloud_available(),
            "cloud_provider": "openai" if os.environ.get("OPENAI_API_KEY") else (
                "stability" if os.environ.get("STABILITY_API_KEY") else None
            ),
        },
    )


def register_generation_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="gen.text_to_image",
            name="Generate Image",
            description="Generate an image from a text prompt. Requires a configured cloud provider (OpenAI/Stability) since no local image-generation runtime is bundled.",
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["prompt"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=180,
            side_effect=ToolSideEffect.EXTERNAL_NETWORK,
            tags=["generation", "image", "cloud"],
        ),
        gen_text_to_image_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="gen.status",
            name="Generation Capability Status",
            description="Report which image-generation backends are available",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=5,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["generation", "status"],
        ),
        gen_status_handler,
    )