import os
from pathlib import Path
from typing import Any

try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None
    Image = None

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    # pyautogui import can fail on headless hosts with a display
    # connection error; that is not a fatal import error.
    PYAUTOGUI_AVAILABLE = False
    pyautogui = None

from eternix.core.config import settings
from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.inference.llama_cpp import InferenceBackend, InferenceRequest
from eternix.tools.registry import tool_registry


async def vision_analyze_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    image_path = input_data.get("image_path", "")
    prompt = input_data.get("prompt", "Describe this image in detail.")
    model_path = input_data.get("model_path", "")

    if not image_path:
        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=False,
            error="No image path provided",
        )

    path = Path(image_path)
    if not path.exists():
        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=False,
            error=f"Image not found: {image_path}",
        )

    # Validate image format and size
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    if path.suffix.lower() not in allowed_extensions:
        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=False,
            error=f"Unsupported image format: {path.suffix}. Supported: {', '.join(allowed_extensions)}",
        )

    # Check file size (max 10MB)
    max_size = 10 * 1024 * 1024
    if path.stat().st_size > max_size:
        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=False,
            error=f"Image too large: {path.stat().st_size} bytes (max {max_size})",
        )

    if not model_path:
        model_path = str(settings.models.vision_model_path)

    if not Path(model_path).exists():
        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=False,
            error=f"Vision model not found: {model_path}",
        )

    projector_path = str(settings.models.vision_projector_path)
    if not Path(projector_path).exists():
        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=False,
            error=f"Vision projector not found: {projector_path}",
        )

    # Use inference backend for vision inference
    inference = InferenceBackend(task_store)
    request = InferenceRequest(
        prompt=prompt,
        model=model_path,
        max_tokens=512,
        temperature=0.7,
        images=[str(path)],
        projector_path=projector_path,
    )

    try:
        response = await inference.run_vision_inference_cli(request)
        
        if response.finish_reason == "error":
            return ToolResult(
                tool_id="vision.analyze",
                task_id=task.id,
                success=False,
                error="Vision inference failed",
            )
        elif response.finish_reason == "timeout":
            return ToolResult(
                tool_id="vision.analyze",
                task_id=task.id,
                success=False,
                error="Vision inference timed out",
            )

        output = response.text.strip()

        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=True,
            output={"image_path": image_path, "prompt": prompt, "description": output},
        )
    except Exception as e:
        return ToolResult(
            tool_id="vision.analyze",
            task_id=task.id,
            success=False,
            error=f"Vision analysis failed: {e}",
        )


async def vision_ocr_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    image_path = input_data.get("image_path", "")
    lang = input_data.get("lang", "eng")

    if not image_path:
        return ToolResult(
            tool_id="vision.ocr",
            task_id=task.id,
            success=False,
            error="No image path provided",
        )

    if not TESSERACT_AVAILABLE or pytesseract is None or Image is None:
        return ToolResult(
            tool_id="vision.ocr",
            task_id=task.id,
            success=False,
            error="pytesseract or PIL not installed",
        )

    try:
        path = Path(image_path)
        if not path.exists():
            return ToolResult(
                tool_id="vision.ocr",
                task_id=task.id,
                success=False,
                error=f"Image not found: {image_path}",
            )

        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang=lang)

        return ToolResult(
            tool_id="vision.ocr",
            task_id=task.id,
            success=True,
            output={"image_path": image_path, "text": text, "lang": lang},
        )
    except Exception as e:
        return ToolResult(
            tool_id="vision.ocr",
            task_id=task.id,
            success=False,
            error=f"OCR failed: {e}",
        )


async def vision_screenshot_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    output_path = input_data.get("output_path", "/tmp/screenshot.png")
    region = input_data.get("region", None)

    if not PYAUTOGUI_AVAILABLE or pyautogui is None:
        return ToolResult(
            tool_id="vision.screenshot",
            task_id=task.id,
            success=False,
            error="pyautogui not available or no display connection",
        )

    try:
        if region:
            screenshot = pyautogui.screenshot(region=region)
        else:
            screenshot = pyautogui.screenshot()

        screenshot.save(output_path)

        return ToolResult(
            tool_id="vision.screenshot",
            task_id=task.id,
            success=True,
            output={"output_path": output_path, "size": os.path.getsize(output_path)},
        )
    except Exception as e:
        return ToolResult(
            tool_id="vision.screenshot",
            task_id=task.id,
            success=False,
            error=f"Screenshot failed: {e}",
        )


def register_vision_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="vision.analyze",
            name="Analyze Image",
            description="Analyze an image using the vision model",
            input_schema={
                "type": "object",
                "properties": {
                    "image_path": {"type": "string"},
                    "prompt": {"type": "string", "default": "Describe this image in detail."},
                    "model_path": {"type": "string"},
                },
                "required": ["image_path"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=120,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["vision", "analyze", "multimodal"],
        ),
        vision_analyze_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="vision.ocr",
            name="OCR Image",
            description="Extract text from image using OCR",
            input_schema={
                "type": "object",
                "properties": {
                    "image_path": {"type": "string"},
                    "lang": {"type": "string", "default": "eng"},
                },
                "required": ["image_path"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=30,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["vision", "ocr", "text_extraction"],
        ),
        vision_ocr_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="vision.screenshot",
            name="Take Screenshot",
            description="Take a screenshot of the screen or region",
            input_schema={
                "type": "object",
                "properties": {
                    "output_path": {"type": "string", "default": "/tmp/screenshot.png"},
                    "region": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                    },
                },
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=10,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["vision", "screenshot", "desktop"],
        ),
        vision_screenshot_handler,
    )