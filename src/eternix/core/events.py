"""Typed agent event system.

Events flow from the backend execution engine to the frontend over a single
WebSocket connection. Each event carries a correlation id (objective_id and
task_id where relevant) so the frontend can reconstruct state without parsing
free-form model text.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow():
    return datetime.now(UTC)


class EventType(str, Enum):
    CONVERSATION_CREATED = "conversation.created"
    MESSAGE_USER = "message.user"
    MESSAGE_ASSISTANT = "message.assistant"
    MESSAGE_STREAM = "message.stream"
    MESSAGE_COMPLETE = "message.complete"

    OBJECTIVE_CREATED = "objective.created"
    OBJECTIVE_STARTED = "objective.started"
    OBJECTIVE_PLANNING = "objective.planning"
    OBJECTIVE_PLAN_READY = "objective.plan_ready"
    OBJECTIVE_AWAITING_AUTHORIZATION = "objective.awaiting_authorization"
    OBJECTIVE_AUTHORIZED = "objective.authorized"
    OBJECTIVE_RUNNING = "objective.running"
    OBJECTIVE_COMPLETED = "objective.completed"
    OBJECTIVE_FAILED = "objective.failed"
    OBJECTIVE_CANCELLED = "objective.cancelled"

    TASK_CREATED = "task.created"
    TASK_READY = "task.ready"
    TASK_RUNNING = "task.running"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TASK_VERIFYING = "task.verifying"
    TASK_VERIFIED = "task.verified"

    TOOL_SELECTED = "tool.selected"
    TOOL_AUTH_REQUIRED = "tool.auth_required"
    TOOL_EXECUTING = "tool.executing"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"

    MODEL_LOADING = "model.loading"
    MODEL_LOADED = "model.loaded"
    MODEL_UNLOADED = "model.unloaded"
    MODEL_ERROR = "model.error"
    INFERENCE_STARTED = "inference.started"
    INFERENCE_TOKEN = "inference.token"
    INFERENCE_COMPLETED = "inference.completed"

    ARTIFACT_CREATED = "artifact.created"

    STATUS = "status"
    ERROR = "error"
    DIAGNOSTIC = "diagnostic"


class AgentEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: EventType
    timestamp: datetime = Field(default_factory=_utcnow)
    conversation_id: str | None = None
    objective_id: str | None = None
    task_id: str | None = None
    tool_id: str | None = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    severity: str = "info"


class EventBroker:
    """In-process pub/sub for agent events."""

    def __init__(self):
        self._subscribers = []

    def subscribe(self, subscriber):
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber):
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    async def publish(self, event):
        for subscriber in list(self._subscribers):
            try:
                await subscriber.send(event)
            except Exception:
                try:
                    self._subscribers.remove(subscriber)
                except ValueError:
                    pass

    async def publish_all(self, events):
        for event in events:
            await self.publish(event)

    def clear(self):
        self._subscribers.clear()


broker = EventBroker()


def make_event(
    type,
    message="",
    conversation_id=None,
    objective_id=None,
    task_id=None,
    tool_id=None,
    data=None,
    severity="info",
):
    return AgentEvent(
        type=type if isinstance(type, EventType) else EventType(type),
        message=message,
        conversation_id=conversation_id,
        objective_id=objective_id,
        task_id=task_id,
        tool_id=tool_id,
        data=data or {},
        severity=severity,
    )