import asyncio
import os
from pathlib import Path
from typing import Any

from eternix.core.models import Task, ToolDefinition, ToolResult, ToolSideEffect
from eternix.core.task_store import TaskStore
from eternix.tools.registry import tool_registry


def _synthesize_voice(voice_model: Any, text: str, output_path: str) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as f:
        voice_model.synthesize(text, f)


async def audio_transcribe_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    audio_path = input_data.get("audio_path", "")
    model = input_data.get("model", "base")
    language = input_data.get("language", "en")

    if not audio_path:
        return ToolResult(
            tool_id="audio.transcribe",
            task_id=task.id,
            success=False,
            error="No audio path provided",
        )

    path = Path(audio_path)
    if not path.exists():
        return ToolResult(
            tool_id="audio.transcribe",
            task_id=task.id,
            success=False,
            error=f"Audio file not found: {audio_path}",
        )

    try:
        from faster_whisper import WhisperModel

        model_instance = WhisperModel(model, device="cpu", compute_type="int8")
        segments, info = model_instance.transcribe(str(path), language=language)

        text = " ".join([seg.text for seg in segments])

        return ToolResult(
            tool_id="audio.transcribe",
            task_id=task.id,
            success=True,
            output={
                "audio_path": audio_path,
                "text": text,
                "language": info.language,
                "duration": info.duration,
            },
        )
    except ImportError:
        return ToolResult(
            tool_id="audio.transcribe",
            task_id=task.id,
            success=False,
            error="faster-whisper not installed",
        )
    except Exception as e:
        return ToolResult(
            tool_id="audio.transcribe",
            task_id=task.id,
            success=False,
            error=f"Transcription failed: {e}",
        )


async def audio_synthesize_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    text = input_data.get("text", "")
    output_path = input_data.get("output_path", "/tmp/speech.wav")
    voice = input_data.get("voice", "en_US-lessac-medium")

    if not text:
        return ToolResult(
            tool_id="audio.synthesize",
            task_id=task.id,
            success=False,
            error="No text provided",
        )

    try:
        from piper_tts import PiperVoice

        voice_model = PiperVoice.load(voice)
        await asyncio.to_thread(_synthesize_voice, voice_model, text, output_path)

        return ToolResult(
            tool_id="audio.synthesize",
            task_id=task.id,
            success=True,
            output={"output_path": output_path, "size": os.path.getsize(output_path)},
        )
    except ImportError:
        return ToolResult(
            tool_id="audio.synthesize",
            task_id=task.id,
            success=False,
            error="piper-tts not installed",
        )
    except Exception as e:
        return ToolResult(
            tool_id="audio.synthesize",
            task_id=task.id,
            success=False,
            error=f"Synthesis failed: {e}",
        )


async def audio_record_handler(input_data: dict[str, Any], task: Task, task_store: TaskStore) -> ToolResult:
    duration = input_data.get("duration", 5)
    output_path = input_data.get("output_path", "/tmp/recording.wav")
    sample_rate = input_data.get("sample_rate", 16000)

    try:
        import sounddevice as sd
        import soundfile as sf

        recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1)
        sd.wait()
        sf.write(output_path, recording, sample_rate)

        return ToolResult(
            tool_id="audio.record",
            task_id=task.id,
            success=True,
            output={"output_path": output_path, "duration": duration, "sample_rate": sample_rate, "size": os.path.getsize(output_path)},
        )
    except ImportError:
        return ToolResult(
            tool_id="audio.record",
            task_id=task.id,
            success=False,
            error="sounddevice or soundfile not installed",
        )
    except Exception as e:
        return ToolResult(
            tool_id="audio.record",
            task_id=task.id,
            success=False,
            error=f"Recording failed: {e}",
        )


def register_audio_tools() -> None:
    tool_registry.register(
        ToolDefinition(
            id="audio.transcribe",
            name="Transcribe Audio",
            description="Transcribe audio to text using Whisper",
            input_schema={
                "type": "object",
                "properties": {
                    "audio_path": {"type": "string"},
                    "model": {"type": "string", "default": "base"},
                    "language": {"type": "string", "default": "en"},
                },
                "required": ["audio_path"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=120,
            side_effect=ToolSideEffect.READ_ONLY,
            tags=["audio", "transcribe", "whisper"],
        ),
        audio_transcribe_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="audio.synthesize",
            name="Synthesize Speech",
            description="Convert text to speech using Piper TTS",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "output_path": {"type": "string", "default": "/tmp/speech.wav"},
                    "voice": {"type": "string", "default": "en_US-lessac-medium"},
                },
                "required": ["text"],
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=60,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["audio", "synthesize", "tts", "piper"],
        ),
        audio_synthesize_handler,
    )

    tool_registry.register(
        ToolDefinition(
            id="audio.record",
            name="Record Audio",
            description="Record audio from microphone",
            input_schema={
                "type": "object",
                "properties": {
                    "duration": {"type": "integer", "default": 5},
                    "output_path": {"type": "string", "default": "/tmp/recording.wav"},
                    "sample_rate": {"type": "integer", "default": 16000},
                },
            },
            output_schema={"type": "object"},
            execution_backend="python",
            timeout=60,
            side_effect=ToolSideEffect.MODIFIES_FILES,
            tags=["audio", "record", "microphone"],
        ),
        audio_record_handler,
    )