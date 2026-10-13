from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from eternix.core.config import settings
from eternix.core.models import (
    Capability,
    CapabilityStatus,
    ConversationDetail,
    ModelInfo,
    Objective,
    Task,
    TaskPriority,
    TaskStatus,
    ToolResult,
)

Base = declarative_base()


class ObjectiveORM(Base):
    __tablename__ = "objectives"

    id = Column(String(36), primary_key=True)
    user_input = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    desired_end_state = Column(Text, nullable=False)
    verification_criteria = Column(JSON, default=list)
    constraints = Column(JSON, default=list)
    required_capabilities = Column(JSON, default=list)
    input_files = Column(JSON, default=list)
    context = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class TaskORM(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    objective_id = Column(String(36), ForeignKey("objectives.id"), nullable=False)
    parent_task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    description = Column(Text, nullable=False)
    capability = Column(String(255), nullable=False)
    tool_id = Column(String(255), nullable=True)
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    depends_on = Column(JSON, default=list)
    status = Column(String(50), nullable=False, default=TaskStatus.CREATED.value)
    priority = Column(Integer, nullable=False, default=50)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    error = Column(Text, nullable=True)
    verification_result = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    objective = relationship("ObjectiveORM", backref="tasks")
    parent = relationship("TaskORM", remote_side=[id], backref="children")


class ToolResultORM(Base):
    __tablename__ = "tool_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_id = Column(String(255), nullable=False)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    success = Column(Integer, nullable=False)
    output = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    exit_code = Column(Integer, nullable=True)
    stdout = Column(Text, default="")
    stderr = Column(Text, default="")
    duration_ms = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=False)


class CapabilityORM(Base):
    __tablename__ = "capabilities"

    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default=CapabilityStatus.MISSING.value)
    required_tools = Column(JSON, default=list)
    model_requirements = Column(JSON, default=list)
    runtime_requirements = Column(JSON, default=list)
    version = Column(String(100), nullable=True)
    provenance = Column(JSON, default=dict)
    last_verified = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)


class ConversationORM(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True)
    title = Column(Text, nullable=False)
    objective_id = Column(String(36), ForeignKey("objectives.id"), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class MessageORM(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    message_metadata = Column(JSON, default=dict)


class WorkspaceORM(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    path = Column(Text, nullable=False, unique=True)
    active = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=False)


class ModelInfoORM(Base):
    __tablename__ = "models"

    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    path = Column(Text, nullable=False)
    format = Column(String(50), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    quantization = Column(String(100), nullable=True)
    context_length = Column(Integer, nullable=False)
    capabilities = Column(JSON, default=list)
    runtime = Column(String(100), nullable=False)
    available = Column(Integer, default=0)
    last_tested = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)


class TaskStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.db_path
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self.Session = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_objective(self, objective: Objective) -> Objective:
        with self.session() as s:
            orm = ObjectiveORM(
                id=str(objective.id),
                user_input=objective.user_input,
                description=objective.description,
                desired_end_state=objective.desired_end_state,
                verification_criteria=objective.verification_criteria,
                constraints=objective.constraints,
                required_capabilities=objective.required_capabilities,
                input_files=objective.input_files,
                context=objective.context,
                created_at=objective.created_at,
                updated_at=objective.updated_at,
            )
            s.add(orm)
        return objective

    def get_objective(self, objective_id: UUID) -> Objective | None:
        with self.session() as s:
            orm = s.get(ObjectiveORM, str(objective_id))
            if not orm:
                return None
            return self._objective_from_orm(orm)

    def update_objective(self, objective: Objective) -> Objective:
        with self.session() as s:
            orm = s.get(ObjectiveORM, str(objective.id))
            if orm:
                orm.user_input = objective.user_input
                orm.description = objective.description
                orm.desired_end_state = objective.desired_end_state
                orm.verification_criteria = objective.verification_criteria
                orm.constraints = objective.constraints
                orm.required_capabilities = objective.required_capabilities
                orm.input_files = objective.input_files
                orm.context = objective.context
                orm.updated_at = objective.updated_at
        return objective

    def create_task(self, task: Task) -> Task:
        with self.session() as s:
            orm = TaskORM(
                id=str(task.id),
                objective_id=str(task.objective_id),
                parent_task_id=str(task.parent_task_id) if task.parent_task_id else None,
                description=task.description,
                capability=task.capability,
                tool_id=task.tool_id,
                input_data=task.input_data,
                output_data=task.output_data,
                depends_on=[str(d) for d in task.depends_on],
                status=task.status.value,
                priority=task.priority.value,
                attempts=task.attempts,
                max_attempts=task.max_attempts,
                error=task.error,
                verification_result=task.verification_result,
                started_at=task.started_at,
                completed_at=task.completed_at,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            s.add(orm)
        return task

    def get_task(self, task_id: UUID) -> Task | None:
        with self.session() as s:
            orm = s.get(TaskORM, str(task_id))
            if not orm:
                return None
            return self._task_from_orm(orm)

    def update_task(self, task: Task) -> Task:
        with self.session() as s:
            orm = s.get(TaskORM, str(task.id))
            if orm:
                orm.description = task.description
                orm.capability = task.capability
                orm.tool_id = task.tool_id
                orm.input_data = task.input_data
                orm.output_data = task.output_data
                orm.depends_on = [str(d) for d in task.depends_on]
                orm.status = task.status.value
                orm.priority = task.priority.value
                orm.attempts = task.attempts
                orm.max_attempts = task.max_attempts
                orm.error = task.error
                orm.verification_result = task.verification_result
                orm.started_at = task.started_at
                orm.completed_at = task.completed_at
                orm.updated_at = task.updated_at
        return task

    def get_tasks_for_objective(self, objective_id: UUID) -> list[Task]:
        with self.session() as s:
            stmt = select(TaskORM).where(TaskORM.objective_id == str(objective_id))
            return [self._task_from_orm(t) for t in s.scalars(stmt)]

    def get_ready_tasks(self, objective_id: UUID) -> list[Task]:
        with self.session() as s:
            stmt = select(TaskORM).where(
                TaskORM.objective_id == str(objective_id),
                TaskORM.status == TaskStatus.READY.value,
            )
            return [self._task_from_orm(t) for t in s.scalars(stmt)]

    def add_tool_result(self, result: ToolResult) -> ToolResult:
        with self.session() as s:
            orm = ToolResultORM(
                tool_id=result.tool_id,
                task_id=str(result.task_id),
                success=1 if result.success else 0,
                output=result.output,
                error=result.error,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=result.duration_ms,
                started_at=result.started_at,
                completed_at=result.completed_at,
            )
            s.add(orm)
        return result

    def get_tool_results(self, task_id: UUID) -> list[ToolResult]:
        with self.session() as s:
            stmt = select(ToolResultORM).where(ToolResultORM.task_id == str(task_id))
            results = []
            for r in s.scalars(stmt):
                results.append(
                    ToolResult(
                        tool_id=r.tool_id,
                        task_id=UUID(r.task_id),
                        success=bool(r.success),
                        output=r.output,
                        error=r.error,
                        exit_code=r.exit_code,
                        stdout=r.stdout,
                        stderr=r.stderr,
                        duration_ms=r.duration_ms,
                        started_at=r.started_at,
                        completed_at=r.completed_at,
                    )
                )
            return results

    def upsert_capability(self, capability: Capability) -> Capability:
        with self.session() as s:
            orm = s.get(CapabilityORM, capability.id)
            if not orm:
                orm = CapabilityORM(id=capability.id)
                s.add(orm)
            orm.name = capability.name
            orm.description = capability.description
            orm.status = capability.status.value
            orm.required_tools = capability.required_tools
            orm.model_requirements = capability.model_requirements
            orm.runtime_requirements = capability.runtime_requirements
            orm.version = capability.version
            orm.provenance = capability.provenance
            orm.last_verified = capability.last_verified
            orm.error = capability.error
        return capability

    def get_capability(self, capability_id: str) -> Capability | None:
        with self.session() as s:
            orm = s.get(CapabilityORM, capability_id)
            if not orm:
                return None
            return Capability(
                id=orm.id,
                name=orm.name,
                description=orm.description,
                status=CapabilityStatus(orm.status),
                required_tools=orm.required_tools,
                model_requirements=orm.model_requirements,
                runtime_requirements=orm.runtime_requirements,
                version=orm.version,
                provenance=orm.provenance,
                last_verified=orm.last_verified,
                error=orm.error,
            )

    def list_capabilities(self) -> list[Capability]:
        with self.session() as s:
            stmt = select(CapabilityORM)
            return [
                Capability(
                    id=orm.id,
                    name=orm.name,
                    description=orm.description,
                    status=CapabilityStatus(orm.status),
                    required_tools=orm.required_tools,
                    model_requirements=orm.model_requirements,
                    runtime_requirements=orm.runtime_requirements,
                    version=orm.version,
                    provenance=orm.provenance,
                    last_verified=orm.last_verified,
                    error=orm.error,
                )
                for orm in s.scalars(stmt)
            ]

    def upsert_model(self, model: ModelInfo) -> ModelInfo:
        with self.session() as s:
            orm = s.get(ModelInfoORM, model.id)
            if not orm:
                orm = ModelInfoORM(id=model.id)
                s.add(orm)
            orm.name = model.name
            orm.path = model.path
            orm.format = model.format
            orm.size_bytes = model.size_bytes
            orm.quantization = model.quantization
            orm.context_length = model.context_length
            orm.capabilities = model.capabilities
            orm.runtime = model.runtime
            orm.available = 1 if model.available else 0
            orm.last_tested = model.last_tested
            orm.error = model.error
        return model

    def get_model(self, model_id: str) -> ModelInfo | None:
        with self.session() as s:
            orm = s.get(ModelInfoORM, model_id)
            if not orm:
                return None
            return ModelInfo(
                id=orm.id,
                name=orm.name,
                path=orm.path,
                format=orm.format,
                size_bytes=orm.size_bytes,
                quantization=orm.quantization,
                context_length=orm.context_length,
                capabilities=orm.capabilities,
                runtime=orm.runtime,
                 available=bool(orm.available),
                 last_tested=orm.last_tested,
                 error=orm.error,
             )

    def create_conversation(self, title: str, objective_id: UUID | None = None) -> tuple[str, str]:
        with self.session() as s:
            conv_id = str(uuid4())
            orm = ConversationORM(
                id=conv_id,
                title=title,
                objective_id=str(objective_id) if objective_id else None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            s.add(orm)
            return conv_id, title

    def list_conversations(self) -> list[dict]:
        with self.session() as s:
            stmt = select(ConversationORM).order_by(ConversationORM.updated_at.desc())
            return [
                {
                    "id": c.id,
                    "title": c.title,
                    "objective_id": c.objective_id,
                    "created_at": c.created_at.isoformat(),
                    "updated_at": c.updated_at.isoformat(),
                    "message_count": 0,
                }
                for c in s.scalars(stmt)
            ]

    def get_conversation(self, conv_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(ConversationORM, conv_id)
            if not orm:
                return None
            msg_stmt = select(MessageORM).where(MessageORM.conversation_id == conv_id).order_by(MessageORM.created_at)
            messages = [
                {
                    "id": m.id,
                    "conversation_id": m.conversation_id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.created_at.isoformat(),
                    "metadata": m.message_metadata or {},
                }
                for m in s.scalars(msg_stmt)
            ]
            return ConversationDetail(
                id=conv_id,
                title=orm.title,
                objective_id=orm.objective_id,
                messages=messages,
            )

    def add_message(self, conv_id: str, role: str, content: str, metadata: dict | None = None) -> str:
        with self.session() as s:
            msg_id = str(uuid4())
            orm = MessageORM(
                id=msg_id,
                conversation_id=conv_id,
                role=role,
                content=content,
                created_at=datetime.now(UTC),
                message_metadata=metadata or {},
            )
            s.add(orm)
            conv = s.get(ConversationORM, conv_id)
            if conv:
                conv.updated_at = datetime.now(UTC)
            return msg_id

    def delete_conversation(self, conv_id: str) -> bool:
        with self.session() as s:
            orm = s.get(ConversationORM, conv_id)
            if not orm:
                return False
            s.delete(orm)
            return True

    def rename_conversation(self, conv_id: str, title: str) -> dict | None:
        with self.session() as s:
            orm = s.get(ConversationORM, conv_id)
            if not orm:
                return None
            orm.title = title
            orm.updated_at = datetime.now(UTC)
            return {"id": conv_id, "title": title}

    def create_workspace(self, name: str, path: str) -> dict:
        with self.session() as s:
            existing = s.scalars(select(WorkspaceORM).where(WorkspaceORM.path == path)).first()
            if existing:
                return {"id": existing.id, "name": existing.name, "path": existing.path, "active": bool(existing.active)}
            ws_id = str(uuid4())
            orm = WorkspaceORM(
                id=ws_id,
                name=name,
                path=path,
                active=0,
                created_at=datetime.now(UTC),
            )
            s.add(orm)
            return {"id": ws_id, "name": name, "path": path, "active": False}

    def list_workspaces(self) -> list[dict]:
        with self.session() as s:
            stmt = select(WorkspaceORM).order_by(WorkspaceORM.created_at.desc())
            return [
                {"id": w.id, "name": w.name, "path": w.path, "active": bool(w.active), "created_at": w.created_at.isoformat()}
                for w in s.scalars(stmt)
            ]

    def get_workspace(self, ws_id: str) -> dict | None:
        with self.session() as s:
            orm = s.get(WorkspaceORM, ws_id)
            if not orm:
                return None
            return {"id": orm.id, "name": orm.name, "path": orm.path, "active": bool(orm.active), "created_at": orm.created_at.isoformat()}

    def delete_workspace(self, ws_id: str) -> bool:
        with self.session() as s:
            orm = s.get(WorkspaceORM, ws_id)
            if not orm:
                return False
            s.delete(orm)
            return True

    def set_active_workspace(self, ws_id: str) -> bool:
        with self.session() as s:
            stmt = select(WorkspaceORM)
            for w in s.scalars(stmt):
                w.active = 1 if w.id == ws_id else 0
            return True

    def get_active_workspace_path(self) -> Path | None:
        """Return the resolved path of the active workspace, if any.

        This is the authoritative confinement root for filesystem and
        command tools. Tools must resolve and validate every path against
        this root instead of the process working directory.
        """
        with self.session() as s:
            ws = s.scalars(select(WorkspaceORM).where(WorkspaceORM.active == 1)).first()
            if ws and ws.path:
                try:
                    return Path(ws.path).resolve()
                except (OSError, ValueError):
                    return None
            return None

    def list_models(self) -> list[ModelInfo]:
        with self.session() as s:
            stmt = select(ModelInfoORM)
            return [
                ModelInfo(
                    id=orm.id,
                    name=orm.name,
                    path=orm.path,
                    format=orm.format,
                    size_bytes=orm.size_bytes,
                    quantization=orm.quantization,
                    context_length=orm.context_length,
                    capabilities=orm.capabilities,
                    runtime=orm.runtime,
                    available=bool(orm.available),
                    last_tested=orm.last_tested,
                    error=orm.error,
                )
                for orm in s.scalars(stmt)
            ]

    def _objective_from_orm(self, orm: ObjectiveORM) -> Objective:
        return Objective(
            id=UUID(orm.id),
            user_input=orm.user_input,
            description=orm.description,
            desired_end_state=orm.desired_end_state,
            verification_criteria=orm.verification_criteria,
            constraints=orm.constraints,
            required_capabilities=orm.required_capabilities,
            input_files=orm.input_files,
            context=orm.context,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def _task_from_orm(self, orm: TaskORM) -> Task:
        return Task(
            id=UUID(orm.id),
            objective_id=UUID(orm.objective_id),
            parent_task_id=UUID(orm.parent_task_id) if orm.parent_task_id else None,
            description=orm.description,
            capability=orm.capability,
            tool_id=orm.tool_id,
            input_data=orm.input_data,
            output_data=orm.output_data,
            depends_on=[UUID(d) for d in orm.depends_on],
            status=TaskStatus(orm.status),
            priority=TaskPriority(orm.priority),
            attempts=orm.attempts,
            max_attempts=orm.max_attempts,
            error=orm.error,
            verification_result=orm.verification_result,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )