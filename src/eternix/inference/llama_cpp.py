import asyncio
from dataclasses import dataclass
from pathlib import Path

from eternix.core.config import settings
from eternix.core.models import ModelInfo
from eternix.core.task_store import TaskStore


@dataclass
class InferenceRequest:
    prompt: str
    model: str
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.95
    stop: list[str] | None = None
    stream: bool = False
    images: list[str] | None = None
    projector_path: str | None = None


@dataclass
class InferenceResponse:
    text: str
    tokens_used: int = 0
    model: str = ""
    finish_reason: str = "stop"


class InferenceBackend:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store
        self.llama_cli = settings.llama_cpp_bin / "llama-cli"
        self.llama_server = settings.llama_cpp_bin / "llama-server"
        self._server_process: asyncio.subprocess.Process | None = None
        self._server_url: str | None = None

    async def discover_models(self) -> list[ModelInfo]:
        models = []
        model_dir = settings.model_dir

        if not model_dir.exists():
            return models

        for model_path in model_dir.rglob("*.gguf"):
            try:
                stat = model_path.stat()
                model_id = model_path.stem
                model = ModelInfo(
                    id=model_id,
                    name=model_path.name,
                    path=str(model_path),
                    format="gguf",
                    size_bytes=stat.st_size,
                    quantization=self._extract_quant(model_path.name),
                    context_length=32768,
                    capabilities=["completion", "chat"],
                    runtime="llama.cpp",
                    available=True,
                )
                models.append(model)
                self.task_store.upsert_model(model)
            except (OSError, TimeoutError):
                pass

        return models

    def _extract_quant(self, filename: str) -> str | None:
        import re
        match = re.search(r"(Q\d+_[KM])", filename, re.IGNORECASE)
        return match.group(1) if match else None

    async def check_model_available(self, model_path: Path) -> bool:
        return model_path.exists() and model_path.stat().st_size > 0

    async def run_inference_cli(self, request: InferenceRequest) -> InferenceResponse:
        model_path = Path(request.model)
        if not model_path.is_absolute():
            model_path = settings.model_dir / request.model

        if not await self.check_model_available(model_path):
            return InferenceResponse(
                text="",
                model=request.model,
                finish_reason="error",
            )

        cmd = [
            str(self.llama_cli),
            "-m", str(model_path),
            "-p", request.prompt,
            "-n", str(request.max_tokens),
            "--temp", str(request.temperature),
            "--top-p", str(request.top_p),
        ]

        if request.projector_path:
            cmd.extend(["--mmproj", request.projector_path])
        
        if request.images:
            for img in request.images:
                cmd.extend(["--image", img])

        if request.stop:
            for stop in request.stop:
                cmd.extend(["--stop", stop])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode != 0:
                return InferenceResponse(
                    text="",
                    model=request.model,
                    finish_reason="error",
                )

            output = stdout.decode("utf-8", errors="replace")
            # Extract just the model response (after the prompt)
            output = self._extract_model_response(output, request.prompt)
            return InferenceResponse(
                text=output.strip(),
                model=request.model,
                finish_reason="stop",
            )
        except TimeoutError:
            return InferenceResponse(
                text="",
                model=request.model,
                finish_reason="timeout",
            )
        except OSError:
            return InferenceResponse(
                text="",
                model=request.model,
                finish_reason="error",
            )

    def _extract_model_response(self, output: str, prompt: str = "") -> str:
        """Extract the actual model response from llama-cli output.

        llama.cpp prints a banner (build/model/ftype/modalities), an
        "available commands:" section, the echoed prompt prefixed by ``> ``,
        then the model's reply.  We strip everything except the reply, and
        never strip legitimate response text that happens to contain a
        banner keyword.
        """
        import re

        # 1. Strip ANSI escape sequences and control characters.
        output = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', output)
        output = re.sub(r'\x1b\][^\x07]*\x07', '', output)  # OSC sequences
        output = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', output)

        # 2. Collapse carriage returns / backspace-driven progress spinners.
        #    The spinner is redrawn in place using \r, so splitting on \n
        #    leaves lines full of ``|/-\`` fragments.
        output = output.replace('\r', '\n')

        lines = output.split('\n')
        cleaned: list[str] = []
        in_commands = False
        seen_prompt = False
        banner_seen = False

        for line in lines:
            stripped = line.strip()

            # Skip spinner-only lines (loading animation).
            if re.fullmatch(r'[\s|\\/\-–>]+', stripped):
                continue

            low = stripped.lower()

            # Skip the llama.cpp banner block.
            if re.fullmatch(r'▄▄ ▄▄|██ ██', stripped):
                banner_seen = True
                continue
            if banner_seen and re.match(
                r'(build|model|ftype|modalities|mmproj)\s*:', low
            ):
                continue
            # Banner ends at the first blank line after the logo.
            if banner_seen and stripped == '':
                banner_seen = False
                continue

            # Skip the "available commands:" section.
            if 'available commands:' in low:
                in_commands = True
                continue
            if in_commands:
                if stripped == '' or stripped.startswith('/'):
                    continue
                in_commands = False

            # Skip the echoed prompt line(s) and everything before them.
            if stripped == '> ' or stripped.startswith('> '):
                seen_prompt = True
                continue
            if not seen_prompt:
                continue

            cleaned.append(line)

        text = '\n'.join(cleaned).strip()

        # 3. Strip trailing status line like ``[ Prompt: 25.1 t/s | ... ]``.
        text = re.sub(r'\s*\[\s*(Prompt|Generation|Load|PP)\s*:.*?\]\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*Exiting\.\.\.\s*', '', text, flags=re.IGNORECASE)

        # 4. If the model echoed the prompt back, drop it.
        if prompt:
            prompt_norm = re.sub(r'\s+', ' ', prompt).strip()
            text_norm = re.sub(r'\s+', ' ', text).strip()
            if text_norm.startswith(prompt_norm):
                text = text[len(prompt_norm):].lstrip()

        # 5. Prefer an explicit JSON object/code-fence when the model emitted one.
        #    Only treat the response as JSON when it starts with ``{`` or ``[``,
        #    otherwise we would strip natural prose that merely contains
        #    brackets (e.g. ``[ Prompt: 32 t/s ]``).
        fence = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
        if fence:
            return fence.group(1).strip()

        stripped_text = text.lstrip()
        if stripped_text[:1] in '{[':
            bare = re.search(r'(\{.*\}|\[.*\])', stripped_text, re.DOTALL)
            if bare and len(bare.group(1)) > len(stripped_text) * 0.6:
                return bare.group(1).strip()

        return text

    async def run_vision_inference_cli(self, request: InferenceRequest) -> InferenceResponse:
        """Run vision inference with image support via llama-cli."""
        return await self.run_inference_cli(request)

    async def start_server(self, model_path: Path, port: int = 8081) -> bool:
        if self._server_process:
            return True

        if not await self.check_model_available(model_path):
            return False

        cmd = [
            str(self.llama_server),
            "-m", str(model_path),
            "--port", str(port),
            "--host", "127.0.0.1",
            "-c", str(settings.max_context_tokens),
        ]

        try:
            self._server_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.sleep(3)
            self._server_url = f"http://127.0.0.1:{port}"
            return True
        except (OSError, TimeoutError):
            return False

    async def stop_server(self) -> None:
        if self._server_process is not None:
            proc = self._server_process
            self._server_process = None
            self._server_url = None
            try:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except (TimeoutError, ProcessLookupError):
                        pass
                if proc.returncode is None:
                    try:
                        proc.kill()
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=3)
                        except (TimeoutError, ProcessLookupError):
                            pass
                    except ProcessLookupError:
                        pass
            except ProcessLookupError:
                pass
            except Exception:
                pass

    async def run_inference_server(self, request: InferenceRequest) -> InferenceResponse:
        if not self._server_url:
            return InferenceResponse(
                text="",
                model=request.model,
                finish_reason="error",
            )

        import httpx

        payload = {
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": request.stream,
        }
        if request.stop:
            payload["stop"] = request.stop

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self._server_url}/completion", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return InferenceResponse(
                        text=data.get("content", ""),
                        tokens_used=data.get("tokens_predicted", 0),
                        model=request.model,
                        finish_reason=data.get("stop_reason", "stop"),
                    )
        except (OSError, TimeoutError):
            pass

        return InferenceResponse(
            text="",
            model=request.model,
            finish_reason="error",
        )


class MockInferenceBackend:
    def __init__(self, task_store: TaskStore):
        self.task_store = task_store

    async def discover_models(self) -> list[ModelInfo]:
        return []

    async def run_inference(self, request: InferenceRequest) -> InferenceResponse:
        return InferenceResponse(
            text=f"[MOCK] Response to: {request.prompt[:100]}...",
            model=request.model,
            finish_reason="stop",
        )