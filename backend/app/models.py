import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True, default="")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="project", lazy="selectin"
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        "ActivityLog", back_populates="project", lazy="selectin"
    )
    memory_snapshots: Mapped[list["MemorySnapshot"]] = relationship(
        "MemorySnapshot", back_populates="project", lazy="selectin"
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        SAEnum(
            "orchestrator",
            "backend",
            "frontend",
            "qa",
            "docs",
            "memory",
            name="agent_type",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SAEnum("idle", "working", "error", name="agent_status"),
        nullable=False,
        default="idle",
    )
    current_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    current_task: Mapped["Task | None"] = relationship(
        "Task", foreign_keys=[current_task_id], lazy="selectin"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(
            "pending",
            "assigned",
            "in_progress",
            "completed",
            "failed",
            name="task_status",
        ),
        nullable=False,
        default="pending",
    )
    assigned_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    parent_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    assigned_agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[assigned_agent_id], lazy="selectin"
    )
    parent_task: Mapped["Task | None"] = relationship(
        "Task", remote_side="Task.id", lazy="selectin"
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=True, default="")
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow)

    project: Mapped["Project"] = relationship("Project", back_populates="activity_logs")
    agent: Mapped["Agent | None"] = relationship("Agent", lazy="selectin")


class MemorySnapshot(Base):
    __tablename__ = "memory_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )
    last_completed: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_blocker: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    project: Mapped["Project"] = relationship(
        "Project", back_populates="memory_snapshots"
    )


# ──────────────────────────────────────────────
# Phase 2: Worker / Remote Execution Models
# ──────────────────────────────────────────────


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=True, default="")
    platform: Mapped[str] = mapped_column(String(50), nullable=True, default="")
    status: Mapped[str] = mapped_column(
        SAEnum("online", "offline", "busy", name="worker_status"),
        nullable=False,
        default="online",
    )
    last_heartbeat: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    sessions: Mapped[list["WorkerSession"]] = relationship(
        "WorkerSession", back_populates="worker", lazy="selectin"
    )


class WorkerSession(Base):
    __tablename__ = "worker_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workers.id"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        SAEnum(
            "idle",
            "running",
            "waiting_input",
            "completed",
            "error",
            name="session_status",
        ),
        nullable=False,
        default="idle",
    )
    last_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    waiting_for_input: Mapped[bool] = mapped_column(default=False)
    input_type: Mapped[str | None] = mapped_column(
        SAEnum("enter", "yes_no", "text", "none", name="input_type_enum"),
        nullable=True,
        default="none",
    )
    input_prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    worker: Mapped["Worker"] = relationship("Worker", back_populates="sessions")
    task: Mapped["Task"] = relationship("Task")
    agent: Mapped["Agent | None"] = relationship("Agent")
    logs: Mapped[list["WorkerLog"]] = relationship(
        "WorkerLog", back_populates="session", lazy="selectin"
    )
    decisions: Mapped[list["AutonomousDecision"]] = relationship(
        "AutonomousDecision", back_populates="session", lazy="selectin"
    )


class WorkerLog(Base):
    __tablename__ = "worker_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("worker_sessions.id"), nullable=False
    )
    level: Mapped[str] = mapped_column(
        SAEnum("info", "warn", "error", "output", name="log_level"),
        nullable=False,
        default="info",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow)

    session: Mapped["WorkerSession"] = relationship(
        "WorkerSession", back_populates="logs"
    )


class AutonomousDecision(Base):
    __tablename__ = "autonomous_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("worker_sessions.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    auto_resolved: Mapped[bool] = mapped_column(default=True)
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow)

    session: Mapped["WorkerSession"] = relationship(
        "WorkerSession", back_populates="decisions"
    )


# ──────────────────────────────────────────────
# Phase 3: Agent Coordination Models
# ──────────────────────────────────────────────


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    from_agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False
    )
    to_agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False
    )
    message_type: Mapped[str] = mapped_column(
        SAEnum(
            "handoff",
            "request_info",
            "response",
            "blocker",
            "update",
            "complete",
            name="message_type",
        ),
        nullable=False,
        default="update",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "read", "acted_on", name="message_status"),
        nullable=False,
        default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    project: Mapped["Project"] = relationship("Project")
    task: Mapped["Task | None"] = relationship("Task")
    from_agent: Mapped["Agent"] = relationship(
        "Agent", foreign_keys=[from_agent_id], lazy="selectin"
    )
    to_agent: Mapped["Agent"] = relationship(
        "Agent", foreign_keys=[to_agent_id], lazy="selectin"
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False
    )
    depends_on_task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "satisfied", name="dependency_status"),
        nullable=False,
        default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    satisfied_at: Mapped[datetime | None] = mapped_column(nullable=True)

    task: Mapped["Task"] = relationship(
        "Task", foreign_keys=[task_id], lazy="selectin"
    )
    depends_on_task: Mapped["Task"] = relationship(
        "Task", foreign_keys=[depends_on_task_id], lazy="selectin"
    )


# ──────────────────────────────────────────────
# Phase 3A: Brainstorm System
# ──────────────────────────────────────────────


class BrainstormRoom(Base):
    __tablename__ = "brainstorm_rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    idea_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(
            "brainstorming",
            "refining",
            "ready_to_spawn",
            "spawned",
            name="brainstorm_status",
        ),
        nullable=False,
        default="brainstorming",
    )
    current_round: Mapped[int] = mapped_column(default=0)
    max_rounds: Mapped[int] = mapped_column(default=3)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal"
    )
    synthesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=True
    )
    spawn_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=_utcnow, onupdate=_utcnow
    )

    project: Mapped["Project | None"] = relationship("Project")
    messages: Mapped[list["BrainstormMessage"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    agents: Mapped[list["BrainstormAgent"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    skills: Mapped[list["BrainstormSkill"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class BrainstormMessage(Base):
    __tablename__ = "brainstorm_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brainstorm_rooms.id"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brainstorm_agents.id"), nullable=True
    )
    agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[str] = mapped_column(
        SAEnum("user", "agent", "system", name="brainstorm_msg_role"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(
        SAEnum(
            "idea",
            "question",
            "analysis",
            "risk",
            "suggestion",
            "plan",
            "challenge",
            name="brainstorm_msg_type",
        ),
        nullable=False,
        default="idea",
    )
    round_number: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    room: Mapped["BrainstormRoom"] = relationship(back_populates="messages")
    agent: Mapped["BrainstormAgent | None"] = relationship(
        back_populates="messages"
    )


class BrainstormAgent(Base):
    __tablename__ = "brainstorm_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brainstorm_rooms.id"), nullable=False
    )
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum("active", "paused", "completed", name="brainstorm_agent_status"),
        nullable=False,
        default="active",
    )
    turn_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    room: Mapped["BrainstormRoom"] = relationship(back_populates="agents")
    messages: Mapped[list["BrainstormMessage"]] = relationship(
        back_populates="agent"
    )


class BrainstormSkill(Base):
    __tablename__ = "brainstorm_skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brainstorm_rooms.id"), nullable=False
    )
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    relevance_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(
            "suggested",
            "accepted",
            "rejected",
            "locked",
            name="brainstorm_skill_status",
        ),
        nullable=False,
        default="suggested",
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    room: Mapped["BrainstormRoom"] = relationship(back_populates="skills")
