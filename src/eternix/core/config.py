"""ETERNIX configuration — single coherent source of truth.

Paths are resolved relative to the repository root so the application works
regardless of the current working directory. Environment variables override
defaults when present.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: this file lives at <root>/src/eternix/core/config.py
REPO_ROOT = Path(__file__).resolve().parents[3]


class ModelConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MODEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    reasoning_model: str = "Qwen3-4B-Q4_K_M.gguf"
    reasoning_model_path: Path = Field(
        default=REPO_ROOT / "models" / "qwen3-4b" / "Qwen3-4B-Q4_K_M.gguf"
    )
    reasoning_model_repo: str = "Qwen/Qwen3-4B-GGUF"

    coding_model: str = "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"
    coding_model_path: Path = Field(
        default=REPO_ROOT / "models" / "qwen-coder-1.5b" / "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
    )
    coding_model_repo: str = "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF"

    vision_model: str = "Qwen3VL-2B-Instruct-Q4_K_M.gguf"
    vision_model_path: Path = Field(
        default=REPO_ROOT / "models" / "qwen-vl-2b" / "Qwen3VL-2B-Instruct-Q4_K_M.gguf"
    )
    vision_model_repo: str = "Qwen/Qwen3-VL-2B-Instruct-GGUF"
    vision_projector: str = "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"
    vision_projector_path: Path = Field(
        default=REPO_ROOT / "models" / "qwen-vl-2b" / "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"
    )

    embedding_model: str = "Qwen3-Embedding-0.6B-Q8_0.gguf"
    embedding_model_path: Path = Field(
        default=REPO_ROOT / "models" / "qwen3-embedding-0.6b" / "Qwen3-Embedding-0.6B-Q8_0.gguf"
    )
    embedding_model_repo: str = "Qwen/Qwen3-Embedding-0.6B-GGUF"

    fallback_model: str = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    fallback_model_path: Path = Field(
        default=REPO_ROOT / "models" / "qwen2.5-1.5b" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    )
    fallback_model_repo: str = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ETERNIX"
    app_version: str = "0.1.0"
    debug: bool = False

    # Directory layout — all under the repository root
    data_dir: Path = Field(default=REPO_ROOT / "data")
    model_dir: Path = Field(default=REPO_ROOT / "models")
    hf_cache_dir: Path = Field(default=REPO_ROOT / "huggingface-cache")

    llama_cpp_bin: Path = Field(default=REPO_ROOT / "build" / "llama.cpp" / "bin")
    llama_cpp_model: Path = Field(
        default=REPO_ROOT / "models" / "qwen-vl-2b" / "Qwen3VL-2B-Instruct-Q4_K_M.gguf"
    )

    db_path: Path = Field(default=REPO_ROOT / "data" / "eternix.db")

    api_host: str = "127.0.0.1"
    api_port: int = 8080

    log_level: str = "INFO"
    log_format: str = "json"

    # Resource-aware inference limits for ~8 GB RAM / no GPU
    max_context_tokens: int = 4096
    default_temperature: float = 0.7
    default_top_p: float = 0.95
    max_inference_tokens: int = 1024

    task_timeout: int = 300
    tool_timeout: int = 60

    enable_voice: bool = False
    enable_vision: bool = True
    enable_web: bool = True

    # Memory settings
    qdrant_path: Path = Field(default=REPO_ROOT / "data" / "qdrant")
    embedding_dim: int = 1024
    memory_collection: str = "eternix_memory"

    # Model configs
    models: ModelConfig = Field(default_factory=ModelConfig)

    # Workspace / sandbox
    default_workspace: Path = Field(default=REPO_ROOT)
    max_workspace_files: int = 200
    max_file_size_bytes: int = 5 * 1024 * 1024

    # Execution / permission defaults
    require_auth_for_destructive: bool = True
    require_auth_for_system: bool = True
    require_auth_for_network: bool = False
    max_concurrent_tools: int = 4
    max_command_output_bytes: int = 100_000


settings = Settings()


def ensure_dirs() -> None:
    """Create all required data directories."""
    for path in [
        settings.data_dir,
        settings.model_dir,
        settings.hf_cache_dir,
        settings.qdrant_path,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    for model_dir in [
        settings.models.reasoning_model_path.parent,
        settings.models.coding_model_path.parent,
        settings.models.vision_model_path.parent,
        settings.models.embedding_model_path.parent,
        settings.models.fallback_model_path.parent,
    ]:
        model_dir.mkdir(parents=True, exist_ok=True)