"""ETERNIX core data models."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow():
    return datetime.now(UTC)


class TaskStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    WAITING_DEPENDENCY = "waiting_dependency"
    WAITING_USER = "waiting_user"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


class ToolSideEffect(str, Enum):
    NONE = "none"
    READ_ONLY = "read_only"
    MODIFIES_FILES = "modifies_files"
    MODIFIES_SYSTEM = "modifies_system"
    EXTERNAL_NETWORK = "external_network"
    DESTRUCTIVE = "destructive"


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    INSTALLED_UNVERIFIED = "installed_unverified"
    MISSING = "missing"
    UNAVAILABLE_PLATFORM = "unavailable_platform"
    WAITING_CREDENTIAL = "waiting_credential"
    WAITING_MODEL = "waiting_model"
    FAILED_INIT = "failed_init"


class PermissionState(str, Enum):
    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"
    AWAITING_AUTHORIZATION = "awaiting_authorization"
    AUTHORIZED = "authorized"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactType(str, Enum):
    FILE = "file"
    IMAGE = "image"
    CHART = "chart"
    DOCUMENT = "document"
    DATA = "data"
    TEXT = "text"


class Objective(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_input: str
    description: str
    desired_end_state: str = "Objective completed successfully"
    verification_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    input_files: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    objective_id: UUID
    parent_task_id: UUID | None = None
    description: str
    capability: str
    tool_id: str | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[UUID] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.CREATED
    priority: TaskPriority = TaskPriority.NORMAL
    attempts: int = 0
    max_attempts: int = 3
    error: str | None = None
    verification_result: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    required_permissions: list[str] = Field(default_factory=list)
    execution_backend: str = "python"
    timeout: int = 60
    side_effect: ToolSideEffect = ToolSideEffect.NONE
    verification_method: str | None = None
    tags: list[str] = Field(default_factory=list)
    category: str = "general"
    enabled: bool = True
    health: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_id: str
    task_id: UUID
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime = Field(default_factory=_utcnow)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None


class Capability(BaseModel):
    id: str
    name: str
    description: str
    status: CapabilityStatus = CapabilityStatus.MISSING
    required_tools: list[str] = Field(default_factory=list)
    model_requirements: list[str] = Field(default_factory=list)
    runtime_requirements: list[str] = Field(default_factory=list)
    version: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    last_verified: datetime | None = None
    error: str | None = None


class ModelInfo(BaseModel):
    id: str
    name: str
    path: str
    format: str
    size_bytes: int
    quantization: str | None = None
    context_length: int
    capabilities: list[str] = Field(default_factory=list)
    runtime: str
    available: bool = False
    loaded: bool = False
    last_tested: datetime | None = None
    error: str | None = None


class Artifact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID | None = None
    objective_id: UUID | None = None
    type: ArtifactType = ArtifactType.FILE
    path: str
    name: str
    mime_type: str | None = None
    size_bytes: int = 0
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class ConversationBase(BaseModel):
    id: str
    title: str
    objective_id: str | None = None
    message_count: int = 0
    created_at: str
    updated_at: str


class ConversationResponse(BaseModel):
    id: str
    title: str
    objective_id: str | None = None


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationDetail(BaseModel):
    id: str
    title: str
    objective_id: str | None = None
    messages: list[MessageResponse] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    objective_id: str | None = None


class MessageCreate(BaseModel):
    role: str = "user"
    content: str
    objective_id: str | None = None


class WorkspaceRegisterRequest(BaseModel):
    path: str
    name: str | None = None


class FileWriteRequest(BaseModel):
    path: str
    content: str
    workspace_id: str | None = None


class FileCreateRequest(BaseModel):
    path: str
    content: str = ""
    workspace_id: str | None = None


class FileDeleteRequest(BaseModel):
    path: str
    workspace_id: str | None = None