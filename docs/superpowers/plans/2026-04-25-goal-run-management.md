# Goal/Run Management Layer — Implementation Plan

**Goal:** Add Goal (high-level intent) and Run (observable execution record) models with timeline events, API, dashboard display, and agent performance — all additive.

**Architecture:** Parallel models approach. New Goal, Run, RunEvent tables. Task gets nullable goal_id FK. RunManager service orchestrates lifecycle. Existing Task/Agent/Worker behavior untouched.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (async), SQLite, Next.js 14, TypeScript

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/services/run_manager.py` | Run lifecycle + events + performance queries |
| `backend/app/api/goals.py` | Goal CRUD API routes |
| `backend/app/api/runs.py` | Run query API routes |
| `frontend/components/GoalsPanel.tsx` | Goals list with progress bars |
| `frontend/components/RunsList.tsx` | Active/recent runs with timeline |
| `tests/test_goal_run.py` | E2E tests for Goal/Run/RunEvent/performance |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/models.py` | Add Goal, Run, RunEvent models; add goal_id to Task |
| `backend/app/schemas.py` | Add Goal/Run/RunEvent/Performance schemas |
| `backend/app/database.py` | Import new models |
| `backend/app/main.py` | Register goals + runs routers |
| `backend/app/services/agent_simulator.py` | Create Run + RunEvents during simulation |
| `backend/app/services/model_router.py` | Link RoutingDecision to Run |
| `frontend/lib/types.ts` | Add Goal/Run/RunEvent TypeScript interfaces |
| `frontend/lib/api.ts` | Add Goal/Run API client methods |
| `frontend/app/project/[id]/page.tsx` | Add GoalsPanel + RunsList sections |

---

## Step 1: Data Models

### 1.1 Add Goal model to `backend/app/models.py`

```python
class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned", index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="execution")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    source_goal_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("goals.id"), nullable=True)
    target_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    tasks: Mapped[list["Task"]] = relationship(backref="goal", lazy="selectin")
    runs: Mapped[list["Run"]] = relationship(backref="goal", lazy="selectin")
```

### 1.2 Add Run model to `backend/app/models.py`

```python
class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    goal_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("goals.id"), nullable=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    worker_session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("worker_sessions.id"), nullable=True)
    routing_decision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("routing_decisions.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="simulated")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evaluator_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    events: Mapped[list["RunEvent"]] = relationship(backref="run", lazy="selectin")
```

### 1.3 Add RunEvent model to `backend/app/models.py`

```python
class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
```

### 1.4 Add goal_id to Task model

```python
# Add to existing Task class:
goal_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("goals.id"), nullable=True)
```

### 1.5 Update `backend/app/database.py` imports

Add `Goal, Run, RunEvent` to the import line.

---

## Step 2: API Schemas

### 2.1 Add to `backend/app/schemas.py`

New schemas:
- `GoalCreate` — title, description, project_id, source, type, target_description
- `GoalUpdate` — status, title, description (all optional)
- `GoalResponse` — full goal with all fields
- `GoalProgressResponse` — calculated progress from tasks/runs
- `RunResponse` — run detail with status, timing, links
- `RunEventResponse` — event type, message, timestamp
- `AgentPerformanceResponse` — aggregated stats per agent_type

---

## Step 3: RunManager Service

### 3.1 Create `backend/app/services/run_manager.py`

Methods:
- `create_run(task_id, goal_id, project_id, agent_type)` → Run
- `add_event(run_id, event_type, message, metadata)` → RunEvent
- `update_status(run_id, status, error_message)` → Run
- `complete_run(run_id, duration_seconds, evaluator_status)` → Run
- `get_goal_progress(goal_id)` → GoalProgressResponse
- `get_agent_performance(project_id, agent_type)` → AgentPerformanceResponse
- `get_active_runs(project_id)` → list[Run]

---

## Step 4: API Endpoints

### 4.1 Create `backend/app/api/goals.py`

- `GET /api/projects/{id}/goals` — list goals for a project
- `POST /api/projects/{id}/goals` — create a goal
- `GET /api/goals/{id}` — get goal with progress summary
- `PATCH /api/goals/{id}` — update goal status
- `GET /api/goals/{id}/progress` — calculated progress from tasks/runs

### 4.2 Create `backend/app/api/runs.py`

- `GET /api/projects/{id}/runs` — list runs for a project
- `GET /api/goals/{id}/runs` — list runs for a goal
- `GET /api/tasks/{id}/runs` — list runs for a task
- `GET /api/runs/{id}` — run detail with events
- `GET /api/runs/{id}/events` — run timeline events
- `GET /api/runs/{id}/performance` — agent performance from run data

### 4.3 Register routers in `backend/app/main.py`

Add imports and `include_router` calls for goals and runs routers.

---

## Step 5: Frontend Changes

### 5.1 Add TypeScript interfaces to `frontend/lib/types.ts`

- Goal, GoalProgress, Run, RunEvent, AgentPerformance interfaces

### 5.2 Add API methods to `frontend/lib/api.ts`

- getGoals, createGoal, getGoal, updateGoal, getGoalProgress
- getProjectRuns, getGoalRuns, getTaskRuns, getRun, getRunEvents, getRunPerformance

### 5.3 Create `frontend/components/GoalsPanel.tsx`

Goals list with:
- Title, status badge, progress bar
- Expand to show tasks and run status
- Create goal input

### 5.4 Create `frontend/components/RunsList.tsx`

Active/recent runs with:
- Status icon, agent_type, execution_mode, provider/model, duration, retry count
- Color-coded status
- Expand run timeline (RunEvents)

### 5.5 Integrate into `frontend/app/project/[id]/page.tsx`

Add GoalsPanel and RunsList sections to project dashboard.

---

## Step 6: Integration Points

### 6.1 Modify `backend/app/services/agent_simulator.py`

- Call `RunManager.create_run()` when task execution starts
- Add RunEvents: `started`, `provider_selected`, `completed`/`failed`
- Call `RunManager.complete_run()` when task finishes

### 6.2 Modify `backend/app/services/model_router.py`

- After provider selection, create `model_selected` RunEvent
- Link RoutingDecision to Run via routing_decision_id

### 6.3 Modify `worker/task_runner.py`

- Post RunEvents via HTTP during execution: `command_executed`, `output_received`, `prompt_detected`, `auto_resolved`, `escalated`

---

## Step 7: Verification Plan

1. **Model creation**: Run app, check DB tables created (goals, runs, run_events)
2. **Goal CRUD**: Create, list, update, get progress via API
3. **Run lifecycle**: Create run, add events, complete/fail run
4. **Agent performance**: Query performance stats from completed runs
5. **Frontend**: View goals panel and runs list in project dashboard
6. **Integration**: Simulate task → verify Run + RunEvents created
7. **Backward compatibility**: Tasks without goals work exactly as before

---

## Step 8: Acceptance Criteria

- [ ] Goal, Run, RunEvent tables created in DB
- [ ] Task model has nullable goal_id FK
- [ ] All Goal CRUD endpoints working
- [ ] All Run query endpoints working
- [ ] RunManager creates runs and events during simulation
- [ ] ModelRouter links routing decisions to runs
- [ ] Goal progress calculated correctly from task/run states
- [ ] Agent performance stats queryable
- [ ] GoalsPanel renders goals with progress bars
- [ ] RunsList renders active/recent runs with timeline
- [ ] All existing functionality preserved (backward compatible)
- [ ] Tests pass for Goal/Run/RunEvent lifecycle
