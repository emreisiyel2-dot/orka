# Goal/Run Management Layer Design

Date: 2026-04-25
Status: Draft
Scope: Phase 3C

## Summary

Add a Paperclip-inspired Goal/Run management layer to ORKA. Goals represent high-level user intent inside a Project. Runs are observable execution records linked to Tasks, WorkerSessions, and RoutingDecisions. RunEvents provide detailed execution timelines. All changes are additive — existing Phase 1/2/3A/3B behavior is preserved.

## Architecture

### Hierarchy

```
Project (existing, unchanged)
├── Goal (new)
│   ├── Task (existing, gets nullable goal_id)
│   └── Run (new, execution attempt of a task)
│       ├── RunEvent (new, append-only timeline)
│       ├── → WorkerSession (optional link)
│       └── → RoutingDecision (optional link)
```

### Approach: Parallel Models

New Goal, Run, and RunEvent tables alongside existing models. Task gets one nullable FK (`goal_id`). Run links to existing infrastructure (WorkerSession, RoutingDecision) but does not replace them. Tasks without Goals work exactly as before.

## Components

### 1. Goal Model

**File**: `backend/app/models.py` (additive)

```python
class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    # "planned" | "active" | "completed" | "paused" | "abandoned"
    # Future-ready: "proposed" | "approved" | "archived"
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="execution")
    # "execution" (default) | "research" | "improvement"
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # "user" | "brainstorm" | "auto"
    source_goal_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("goals.id"), nullable=True)
    # R&D traceability: links improvement/research goals back to original goal
    target_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(backref="goal", lazy="selectin")
    runs: Mapped[list["Run"]] = relationship(backref="goal", lazy="selectin")
```

### 2. Run Model

**File**: `backend/app/models.py` (additive)

```python
class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    goal_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("goals.id"), nullable=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    worker_session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("worker_sessions.id"), nullable=True)
    routing_decision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("routing_decisions.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="simulated")
    # "cli" | "api" | "simulated" — self-descriptive, do not rely only on RoutingDecision
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Run status enum (strict):
    #   "pending"    — created, not yet started
    #   "running"    — actively executing
    #   "completed"  — finished successfully
    #   "failed"     — ended with error (see failure_type)
    #   "retrying"   — previous run failed, new run about to start
    #   "cancelled"  — user or system cancelled before completion
    #   "blocked"    — quota exhausted or approval required
    #   "paused"     — temporarily suspended, resumable
    # Aligns with: CLIQuotaTracker states, Task retries, approval flows
    retry_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Lightweight failure classification (nullable, only set when status="failed"):
    #   "model_error"         — LLM or CLI model returned an error
    #   "cli_error"           — CLI binary crashed or not found
    #   "timeout"             — execution exceeded time limit
    #   "quota_block"         — CLI or API quota exhausted
    #   "validation_failed"   — output did not pass evaluator checks
    evaluator_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "pending" | "passed" | "failed" | "skipped"
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    # Relationships
    events: Mapped[list["RunEvent"]] = relationship(backref="run", lazy="selectin")
```

### 3. RunEvent Model

**File**: `backend/app/models.py` (additive)

```python
class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "cli" | "api" | "simulated" — links event to execution layer
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # e.g. "claude_code", "openai", "openrouter" — which provider handled this event
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # e.g. "claude-sonnet-4-6", "gpt-4o" — which model was used
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
```

Event types (15):
`started`, `task_assigned`, `provider_selected`, `model_selected`, `quota_checked`, `command_executed`, `output_received`, `prompt_detected`, `auto_resolved`, `escalated`, `evaluator_reviewed`, `retried`, `completed`, `failed`, `paused`

### 4. Task Model Change

**File**: `backend/app/models.py` (additive — one nullable FK)

Add to existing Task model:
```python
goal_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("goals.id"), nullable=True)
```

Tasks without a goal work exactly as before.

### 5. API Schemas

**File**: `backend/app/schemas.py` (additive)

New schemas:
- `GoalCreate` — title, description, project_id, source, target_description
- `GoalResponse` — full goal with status, type, progress
- `GoalProgressResponse` — calculated progress from tasks/runs
- `RunResponse` — run detail with status, timing, links
- `RunEventResponse` — event type, message, timestamp
- `AgentPerformanceResponse` — aggregated stats per agent_type

### 6. API Endpoints

**Goals:**
- `GET /api/projects/{id}/goals` — list goals for a project
- `POST /api/projects/{id}/goals` — create a goal
- `GET /api/goals/{id}` — get goal with progress summary
- `PATCH /api/goals/{id}` — update goal status
- `GET /api/goals/{id}/progress` — calculated progress from tasks/runs

**Runs:**
- `GET /api/projects/{id}/runs` — list runs for a project
- `GET /api/goals/{id}/runs` — list runs for a goal
- `GET /api/tasks/{id}/runs` — list runs for a task
- `GET /api/runs/{id}` — run detail with events
- `GET /api/runs/{id}/events` — run timeline events
- `GET /api/runs/{id}/performance` — agent performance from run data

### 7. RunManager Service

**File**: `backend/app/services/run_manager.py` (new)

Methods:
- `create_run(task_id, goal_id, project_id, agent_type)` → Run
- `add_event(run_id, event_type, message, metadata)` → RunEvent
- `update_status(run_id, status, error_message)` → Run
- `complete_run(run_id, duration_seconds, evaluator_status)` → Run
- `get_goal_progress(goal_id)` → GoalProgressResponse
- `get_agent_performance(project_id, agent_type)` → AgentPerformanceResponse
- `get_active_runs(project_id)` → list[Run]

Integration points:
- `AgentSimulator` calls `create_run` when task execution starts
- `ModelRouter.route()` links routing decision to run after provider selection
- `TaskRunner` appends RunEvents during execution

### 8. Frontend Dashboard Extensions

**File**: `frontend/` (modify existing project dashboard)

**Goals Panel:**
- List of goals with title, status badge, progress bar
- Click to expand: shows tasks and their run status
- Create goal from input field or from brainstorm

**Active Runs List:**
- Compact list: status icon, agent_type, execution_mode, provider/model, duration, retry count
- Color-coded: green=completed, blue=running, red=failed, yellow=retried
- Click to expand run timeline (RunEvents)

**Agent Performance Stats:**
- Per-agent summary table: success rate, avg duration, task count, retry rate
- Queried on-the-fly from Run records via API

### 9. Agent Performance (On-the-fly)

Calculated from Run records, no separate stats table:

```python
agent_stats = {
    "agent_type": "backend",
    "total_runs": 42,
    "completed": 38,
    "failed": 4,
    "success_rate": 0.90,
    "avg_duration_seconds": 12.3,
    "retry_rate": 0.07,
    "by_execution_mode": {"cli": 30, "api": 12},
    "by_provider": {"claude_code": 30, "openai": 12}
}
```

## Goal Progress Calculation

Goal progress is calculated from its tasks and their latest runs:

```python
progress = {
    "total_tasks": 5,
    "completed_tasks": 3,
    "progress_percent": 60.0,
    "status": "active"  # derived from task completion
}
```

**Rule: A task is considered completed if its latest Run.status == "completed".**

If a task has no runs yet, it counts as "pending". If its latest run is "failed" or "retrying", the task counts as "in_progress". Only "completed" runs move the progress bar forward.

Progress derivation:
- All tasks completed → goal status = "completed"
- Any task failed (latest run) → goal status stays "active"
- No tasks have runs → goal status = "planned"

## Retry Semantics

- A retry creates a **new Run** record with `retry_count` incremented
- Previous Runs are **immutable** — their status, events, and timing never change
- The new Run links to the same `task_id` and `goal_id`
- `retry_count` on the new Run = previous run's `retry_count + 1`
- The previous Run's status remains "failed" (not changed to "retrying")
- The new Run starts with status "pending", then transitions to "running"

This ensures a complete audit trail: every execution attempt is preserved.

## Database Indexes

Required indexes for query performance:

```sql
CREATE INDEX ix_runs_task_id ON runs(task_id);
CREATE INDEX ix_runs_goal_id ON runs(goal_id);
CREATE INDEX ix_runs_status ON runs(status);
CREATE INDEX ix_runs_project_id ON runs(project_id);
CREATE INDEX ix_run_events_run_id ON run_events(run_id, created_at);
CREATE INDEX ix_goals_project_id ON goals(project_id);
CREATE INDEX ix_goals_status ON goals(status);
```

In SQLAlchemy, add `index=True` to the relevant mapped_column definitions.

## What Stays the Same

- All existing models (Project, Task, Agent, Worker, WorkerSession, etc.)
- All existing API endpoints
- All existing frontend functionality
- Phase 1/2/3A/3B behavior completely preserved
- Tasks without Goals work exactly as before
- WorkerSessions continue independently of Runs

## What Gets Removed / Deprecated

Nothing removed. All changes are additive.

## New Files Summary

| File | Purpose |
|------|---------|
| `backend/app/services/run_manager.py` | Run lifecycle management service |
| `tests/test_goal_run.py` | Unit tests for Goal, Run, RunEvent, performance |

## Modified Files Summary

| File | Change |
|------|--------|
| `backend/app/models.py` | Add Goal, Run, RunEvent models; add goal_id to Task |
| `backend/app/schemas.py` | Add Goal/Run/RunEvent/Performance schemas |
| `backend/app/database.py` | Import new models |
| `backend/app/main.py` | Add Goal/Run API endpoints |
| `backend/app/services/agent_simulator.py` | Create Run + RunEvents during simulation |
| `backend/app/services/model_router.py` | Link RoutingDecision to Run |
| `worker/task_runner.py` | Append RunEvents during execution |
| `frontend/` | Goals panel, runs list, agent stats in dashboard |

## Data Flow: Creating a Run

1. User creates a Goal inside a Project
2. User adds Tasks to the Goal (or existing tasks get assigned)
3. Task execution starts (via AgentSimulator or Worker)
4. `RunManager.create_run()` creates a Run record
5. Execution proceeds:
   - `provider_selected` event → RunEvent
   - `model_selected` event → RunEvent
   - `output_received` events → RunEvents
   - `prompt_detected` / `auto_resolved` → RunEvents
6. Execution completes (success or failure)
7. `RunManager.complete_run()` updates status, duration
8. Goal progress recalculated from task/run states

## Data Flow: Agent Performance Query

1. Dashboard requests `GET /api/runs/{id}/performance`
2. `RunManager.get_agent_performance()` queries Run records
3. Aggregates: total, completed, failed, avg_duration, retry_rate
4. Groups by execution_mode and provider
5. Returns AgentPerformanceResponse

## Future-Ready: R&D / Improvement Lab

The Goal model supports future R&D capabilities through:

- `Goal.type`: "execution" (default) | "research" | "improvement"
- `Goal.status`: includes "proposed" | "approved" | "archived"

**Planned R&D flow (not implemented this phase):**
1. User marks a Project/Goal as "send to R&D"
2. ORKA creates a `Goal(type="improvement")`
3. R&D agents analyze: implementation, logs, failures, performance
4. ORKA produces an ImprovementProposal
5. User reviews proposal
6. If approved: proposal becomes implementation tasks → Runs
7. If rejected: archived with reason

**R&D rules (for future implementation):**
- Never auto-modify production code
- Proposals require user approval
- Respect quota and CLI/API limits
- No silent paid fallback
- No uncontrolled agent spawning
- All R&D decisions logged

**Data concepts for future:**
- ImprovementGoal (uses Goal with type="improvement", source_goal_id points to original)
- ResearchRun (uses Run with special metadata)
- ImprovementProposal (new model when R&D phase is built)
- Goal.source_goal_id enables tracing improvement → original execution goal

## Constraints

- All changes additive — nothing removed or renamed
- Tasks without Goals must work exactly as before
- Run creation must not block task execution
- RunEvent append-only — no updates or deletes
- Agent performance calculated on-the-fly (no pre-computed table)
- Existing API endpoints unchanged
- Frontend additions must not clutter dashboard
- Goal.status and Goal.type values extensible for R&D Lab
