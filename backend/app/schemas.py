from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------- Project ----------

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    created_at: datetime


# ---------- Task ----------

class TaskCreate(BaseModel):
    project_id: str
    content: str
    parent_task_id: Optional[str] = None


class TaskAssign(BaseModel):
    agent_id: str


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    content: str
    status: str
    assigned_agent_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime


# ---------- Agent ----------

class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    status: str
    current_task_id: Optional[str] = None
    created_at: datetime


class AgentStatusUpdate(BaseModel):
    status: str


# ---------- Activity Log ----------

class ActivityLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    agent_id: Optional[str] = None
    action: str
    details: str
    timestamp: datetime


# ---------- Memory Snapshot ----------

class MemorySnapshotCreate(BaseModel):
    last_completed: Optional[str] = None
    current_blocker: Optional[str] = None
    next_step: Optional[str] = None


class MemorySnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    last_completed: Optional[str] = None
    current_blocker: Optional[str] = None
    next_step: Optional[str] = None
    updated_at: datetime


# ---------- Summary ----------

class AgentSummary(BaseModel):
    name: str
    type: str
    status: str


class SummaryResponse(BaseModel):
    project_name: str
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    agents: list[AgentSummary]
    recent_activity: list[ActivityLogResponse]
    memory: Optional[MemorySnapshotResponse] = None
    overall_status: str
    message: str


# ──────────────────────────────────────────────
# Phase 2: Worker / Remote Execution
# ──────────────────────────────────────────────


class WorkerRegister(BaseModel):
    name: str
    hostname: str = ""
    platform: str = ""


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    hostname: str
    platform: str
    status: str
    last_heartbeat: datetime
    created_at: datetime


class WorkerSessionCreate(BaseModel):
    worker_id: str
    task_id: str
    agent_id: Optional[str] = None


class WorkerSessionUpdate(BaseModel):
    status: Optional[str] = None
    last_output: Optional[str] = None
    waiting_for_input: Optional[bool] = None
    input_type: Optional[str] = None
    input_prompt_text: Optional[str] = None
    exit_code: Optional[int] = None


class WorkerSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    worker_id: str
    task_id: str
    agent_id: Optional[str] = None
    status: str
    last_output: Optional[str] = None
    waiting_for_input: bool
    input_type: Optional[str] = None
    input_prompt_text: Optional[str] = None
    exit_code: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class WorkerSessionDetail(WorkerSessionResponse):
    logs: list["WorkerLogResponse"] = []
    decisions: list["AutonomousDecisionResponse"] = []


class WorkerLogCreate(BaseModel):
    level: str = "info"
    content: str


class WorkerLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    level: str
    content: str
    timestamp: datetime


class AutonomousDecisionCreate(BaseModel):
    decision: str
    reason: str
    auto_resolved: bool = True


class AutonomousDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    decision: str
    reason: str
    auto_resolved: bool
    timestamp: datetime


class SessionInput(BaseModel):
    input_value: str


class TaskWithSessionsResponse(TaskResponse):
    worker_sessions: list[WorkerSessionResponse] = []


# ──────────────────────────────────────────────
# Phase 3: Agent Coordination
# ──────────────────────────────────────────────


class AgentMessageCreate(BaseModel):
    project_id: str
    task_id: Optional[str] = None
    from_agent_id: str
    to_agent_id: str
    message_type: str = "update"
    content: str
    context: Optional[str] = None


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: Optional[str] = None
    from_agent_id: str
    to_agent_id: str
    message_type: str
    content: str
    context: Optional[str] = None
    status: str
    created_at: datetime
    from_agent_name: Optional[str] = None
    to_agent_name: Optional[str] = None


class TaskDependencyCreate(BaseModel):
    task_id: str
    depends_on_task_id: str


class TaskDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    depends_on_task_id: str
    status: str
    created_at: datetime
    satisfied_at: Optional[datetime] = None
    task_content: Optional[str] = None
    depends_on_content: Optional[str] = None


# ──────────────────────────────────────────────
# Phase 3A: Brainstorm System
# ──────────────────────────────────────────────


class BrainstormRoomCreate(BaseModel):
    idea_text: str
    title: str | None = None
    mode: str = "normal"


class BrainstormRoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    idea_text: str
    status: str
    current_round: int
    max_rounds: int
    mode: str
    synthesis: str | None = None
    project_id: str | None = None
    spawn_plan: str | None = None
    created_at: datetime
    updated_at: datetime


class BrainstormAgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_type: str
    agent_name: str
    status: str
    turn_order: int


class BrainstormMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    room_id: str
    agent_id: str | None = None
    agent_type: str | None = None
    role: str
    content: str
    message_type: str
    round_number: int
    created_at: datetime


class BrainstormSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skill_name: str
    description: str
    relevance_reason: str
    status: str


class BrainstormRoomDetail(BrainstormRoomResponse):
    messages: list[BrainstormMessageResponse] = []
    agents: list[BrainstormAgentResponse] = []
    skills: list[BrainstormSkillResponse] = []


class BrainstormUserMessage(BaseModel):
    content: str
    target_agent_type: str | None = None


class BrainstormSkillUpdate(BaseModel):
    status: str


class BrainstormModeUpdate(BaseModel):
    mode: str  # normal, deep_dive, exploration, decision


# ──────────────────────────────────────────────
# Phase 3A: Spawn Plan Schemas
# ──────────────────────────────────────────────


class SpawnPlanTask(BaseModel):
    title: str
    agent_type: str
    depends_on: list[str] | None = None
    priority: str = "medium"
    estimated_complexity: str = "moderate"


class SpawnPlanRisk(BaseModel):
    description: str
    severity: str
    mitigation: str


class SpawnPlanSkillItem(BaseModel):
    name: str
    description: str
    reason: str


class SpawnPlan(BaseModel):
    project_name: str
    description: str
    tasks: list[SpawnPlanTask]
    architecture_notes: list[str]
    risks: list[SpawnPlanRisk]
    next_steps: list[str]
    skills: list[SpawnPlanSkillItem]


# ──────────────────────────────────────────────
# Phase 3B: Model Routing / Quota / Budget
# ──────────────────────────────────────────────


class ModelInfoResponse(BaseModel):
    id: str
    provider: str
    tier: str
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_tokens: int
    strengths: list[str] = []
    speed: str = "medium"


class ProviderStatusResponse(BaseModel):
    name: str
    healthy: bool
    quota_status: str
    remaining_quota: float | None = None
    total_quota: float | None = None
    reset_at: datetime | None = None
    allow_paid_overage: bool = False
    models: list[ModelInfoResponse] = []


class UsageRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str | None = None
    agent_type: str | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    routing_decision_id: str | None = None
    created_at: datetime


class RoutingDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str | None = None
    agent_type: str | None = None
    requested_tier: str
    selected_model: str
    selected_provider: str
    reason: str
    fallback_from: str | None = None
    quota_status: str
    cost_estimate: float
    actual_cost: float | None = None
    blocked_reason: str | None = None
    execution_mode: str = "api"
    created_at: datetime


class BudgetStatusResponse(BaseModel):
    daily_spend: float
    daily_soft_limit: float
    daily_hard_limit: float
    monthly_spend: float
    monthly_hard_limit: float
    state: str


class BudgetConfigUpdate(BaseModel):
    daily_soft_limit: float | None = None
    daily_hard_limit: float | None = None
    monthly_hard_limit: float | None = None
    per_task_max_cost: float | None = None


class QuotaStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    quota_type: str
    status: str
    remaining_quota: float | None = None
    total_quota: float | None = None
    reset_at: datetime | None = None
    allow_paid_overage: bool
    updated_at: datetime


class PaidOverrideApprove(BaseModel):
    task_id: str
    provider: str
    reason: str


class TaskModelOverride(BaseModel):
    model_id: str
    provider: str


# ──────────────────────────────────────────────
# Phase 3C: Goal/Run Management
# ──────────────────────────────────────────────


class GoalCreate(BaseModel):
    title: str
    description: str = ""
    project_id: str
    source: str = "user"
    type: str = "execution"
    target_description: str = ""


class GoalUpdate(BaseModel):
    status: str | None = None
    title: str | None = None
    description: str | None = None


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    description: str
    status: str
    type: str
    source: str
    source_goal_id: str | None = None
    target_description: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class GoalProgressResponse(BaseModel):
    goal_id: str
    total_tasks: int
    completed_tasks: int
    progress_percent: float
    status: str


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    goal_id: str | None = None
    project_id: str
    agent_type: str
    worker_session_id: str | None = None
    routing_decision_id: str | None = None
    provider: str
    model: str
    execution_mode: str
    status: str
    retry_count: int = 0
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    failure_type: str | None = None
    evaluator_status: str | None = None
    created_at: datetime
    updated_at: datetime


class RunDetailResponse(RunResponse):
    events: list["RunEventResponse"] = []


class RunEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    event_type: str
    execution_mode: str | None = None
    provider: str | None = None
    model: str | None = None
    message: str
    metadata_json: str | None = None
    created_at: datetime


class AgentPerformanceResponse(BaseModel):
    agent_type: str
    total_runs: int
    completed: int
    failed: int
    success_rate: float
    avg_duration_seconds: float
    retry_rate: float
    by_execution_mode: dict[str, int]
    by_provider: dict[str, int]
