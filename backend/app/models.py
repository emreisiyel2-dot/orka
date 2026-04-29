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
    goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=True
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
        String(30),
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


# ──────────────────────────────────────────────
# Phase 3B: Model Routing / Quota / Budget
# ──────────────────────────────────────────────


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    requested_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    selected_model: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    fallback_from: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quota_status: Mapped[str] = mapped_column(String(30), nullable=False, default="available")
    cost_estimate: Mapped[float] = mapped_column(default=0.0)
    actual_cost: Mapped[float | None] = mapped_column(nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="api")
    task_complexity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    selected_cli_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    considered_providers: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_providers: Mapped[str | None] = mapped_column(Text, nullable=True)
    learning_signals_at_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    usage_records: Mapped[list["UsageRecord"]] = relationship(lazy="selectin")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    routing_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("routing_decisions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class BudgetConfigDB(Base):
    __tablename__ = "budget_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    daily_soft_limit: Mapped[float] = mapped_column(default=5.0)
    daily_hard_limit: Mapped[float] = mapped_column(default=10.0)
    monthly_hard_limit: Mapped[float] = mapped_column(default=100.0)
    per_task_max_cost: Mapped[float] = mapped_column(default=1.0)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class ProviderQuotaState(Base):
    __tablename__ = "provider_quota_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    quota_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="available"
    )
    remaining_quota: Mapped[float | None] = mapped_column(nullable=True)
    total_quota: Mapped[float | None] = mapped_column(nullable=True)
    window_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reset_at: Mapped[datetime | None] = mapped_column(nullable=True)
    allow_paid_overage: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


# ──────────────────────────────────────────────
# Phase 3C: Goal/Run Management
# ──────────────────────────────────────────────


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned", index=True,
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="execution")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    source_goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=True
    )
    target_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    tasks: Mapped[list["Task"]] = relationship(backref="goal", lazy="selectin")
    runs: Mapped[list["Run"]] = relationship(backref="goal", lazy="selectin")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False, index=True,
    )
    goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=True, index=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True,
    )
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    worker_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("worker_sessions.id"), nullable=True
    )
    routing_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("routing_decisions.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    execution_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="simulated"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
    )
    retry_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evaluator_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    feedback_score: Mapped[float | None] = mapped_column(nullable=True)
    failure_classification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    retry_eligible: Mapped[bool | None] = mapped_column(default=None)
    retry_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    events: Mapped[list["RunEvent"]] = relationship(backref="run", lazy="selectin")


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class RunEventArchive(Base):
    __tablename__ = "run_event_archives"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class DailyStats(Base):
    __tablename__ = "daily_stats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    total_runs: Mapped[int] = mapped_column(default=0)
    failed_runs: Mapped[int] = mapped_column(default=0)
    avg_duration_seconds: Mapped[float] = mapped_column(default=0.0)
    active_cli_sessions: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


# ──────────────────────────────────────────────
# Phase 4: R&D / Improvement Lab
# ──────────────────────────────────────────────


class ImprovementProposal(Base):
    __tablename__ = "improvement_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False, index=True,
    )
    source_goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    # Strict status: draft | under_review | approved | rejected | converted_to_goal | archived
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True,
    )

    # Problem analysis
    problem_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Proposed solution
    suggested_solution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_impact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(
        String(10), nullable=False, default="medium",
    )
    implementation_effort: Mapped[str] = mapped_column(
        String(20), nullable=False, default="moderate",
    )

    # Evidence linking
    related_run_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    related_goal_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    related_task_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    related_agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    related_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    related_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Metadata
    analysis_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="failure_pattern",
    )
    affected_agents: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_areas: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Approval safety guard
    guard_quota_impact: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    guard_risk_assessment: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    guard_approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    guard_approved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Review flow
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Implementation link
    implementation_goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=True,
    )

    # Decision audit trail
    decision_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
