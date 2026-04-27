# Phase 5.5: Reality Hardening — Design Spec

Date: 2026-04-25
Status: Approved
Scope: Phase 5.5
Depends on: Phase 5 (R&D Intelligence Upgrade)

## Summary

Make ORKA stable, predictable, and safe under real-world usage. No new intelligence features. No scope expansion. Focus on reliability and correctness across 6 areas: pagination, guard hardening, session handling, data retention, proposal quality tracking, and minimal observability.

## Problem Statement

Phase 5 delivered intelligent analysis, but the system has reliability gaps that would surface under real load:

| # | Problem | Impact | Fix |
|---|---------|--------|-----|
| 1 | Run/event APIs return unbounded lists | OOM risk, slow responses under load | Add pagination |
| 2 | Goal progress queries N+1 per task | Degrades as task count grows | Batch query |
| 3 | Guard defaults to dev_mode=True | Budget limits bypassed in production | Default to false |
| 4 | Guard silently swallows budget errors | Blocks go undetected | Fail explicitly |
| 5 | CLI executions not tracked as sessions | Stuck CLI runs never cleaned up | Bridge CLI → WorkerSession |
| 6 | RunEvents accumulate forever | Database bloat, slow queries | Archive after 30 days |
| 7 | No daily statistics | No visibility into system health | DailyStats model + endpoint |
| 8 | Proposal decisions not logged | R&D can't learn from past rejections | Decision log |

## Design Decisions

### Decision 1: Pagination with limit/offset, not cursor-based

Simple `limit`/`offset` query params on all unbounded list endpoints. Default limit: 50, **hard cap: 200 — requests exceeding the cap are rejected with 422**. Matches existing patterns in `routing.py` and `sessions.py`.

**Why:** Cursor-based pagination requires ordered unique columns and is harder for frontend consumers. For ORKA's scale (hundreds of runs, not millions), offset pagination is sufficient and simpler.

### Decision 2: dev_mode defaults to false, explicitly enabled

`ORKA_DEV_MODE` env var defaults to `"false"`. Must be explicitly set to `"true"` to enable advisory budget mode. The guard persists the `dev_mode` flag in its JSON data for auditability.

**Why:** Safe-by-default. A production deployment without the env var gets strict enforcement. Development environments explicitly opt in to relaxed checks.

### Decision 3: CLI executions create WorkerSession records with guaranteed cleanup

When a CLI subprocess starts via `ModelRouter._try_cli_route()`, a WorkerSession is created with status "running". The session update is wrapped in a `finally` block — guaranteed to execute on success, failure, timeout, or any unhandled exception. This makes the existing `_cleanup_stuck_sessions()` background task cover CLI runs too.

**Why:** No new cleanup mechanism needed. The existing 10-minute stuck-session detection works — it just needs CLI runs to be visible. The `finally` guarantee ensures no session is ever left in "running" state regardless of how execution ends.

### Decision 4: Archive table, not delete

New `RunEventArchive` model with same schema as `RunEvent`. A background task moves events older than 30 days from `run_events` to `run_event_archives`. The original rows are then deleted. R&D analysis can query either table.

**Access rule:** The archive table is NOT queried by default. Only `ResearchAnalyzer` and explicit historical query endpoints may read from it. The standard `RunManager` and API layer query `run_events` only — keeping the hot path fast and simple.

**Why:** Deleting outright loses audit trail. A separate table keeps the hot table small while preserving full history. SQLite handles this well — no cross-table foreign keys needed for archives.

### Decision 5: DailyStats snapshot, not live aggregation

New `DailyStats` model written once per day by a background task. Stores per-project: date, total_runs, failed_runs, avg_duration_seconds, active_cli_sessions. The `/api/system/stats` endpoint reads from today's snapshot plus live counts for the current day.

**Why:** Avoids expensive `COUNT`/`AVG` queries on the runs table every time stats are requested. The snapshot is cheap to compute and store.

### Decision 6: Decision log on proposals, not separate model

Add `decision_log` JSON column to `ImprovementProposal`. Each approve/reject/archive action appends an entry. The `ProposalGenerator` reads past decisions to annotate similar new proposals.

**Why:** No new model, no new table, no new API. A JSON column on the existing model is sufficient for the current scale.

## Component Changes

### 1. Pagination for List Endpoints

**File**: `backend/app/api/runs.py`

Add `limit: int = 50, offset: int = 0` query params to all 4 list endpoints:

```python
@router.get("/projects/{project_id}/runs", response_model=list[RunResponse])
async def list_project_runs(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run)
        .where(Run.project_id == project_id)
        .order_by(Run.created_at.desc())
        .limit(limit).offset(offset)
    )
    return list(result.scalars().all())
```

Same pattern for:
- `GET /api/goals/{goal_id}/runs`
- `GET /api/tasks/{task_id}/runs`
- `GET /api/runs/{run_id}/events`

### 2. Goal Progress N+1 Fix

**File**: `backend/app/services/run_manager.py` — `get_goal_progress()` method

Replace per-task query loop with a single batch query:

```python
# Before (N+1):
for task in tasks:
    run_result = await db.execute(
        select(Run).where(Run.task_id == task.id).order_by(Run.created_at.desc()).limit(1)
    )

# After (batch):
task_ids = [t.id for t in tasks]
# Get latest run per task in one query using a subquery
latest_runs = await db.execute(
    select(Run).where(
        Run.task_id.in_(task_ids),
        Run.id.in_(
            select(func.max(Run.id)).where(Run.task_id.in_(task_ids)).group_by(Run.task_id)
        )
    )
)
run_by_task = {r.task_id: r for r in latest_runs.scalars().all()}
completed_tasks = sum(1 for t in tasks if run_by_task.get(t.id) and run_by_task[t.id].status == "completed")
```

### 3. Guard Hardening

**File**: `backend/app/services/rd_manager.py`

#### 3.1 Default dev_mode to false

```python
_DEV_MODE = os.getenv("ORKA_DEV_MODE", "false").lower() == "true"
```

Change from `"true"` to `"false"` as the default.

#### 3.2 Remove silent budget fallback

Replace `except Exception: pass` in budget checking with explicit failure:

```python
try:
    from app.services.budget_manager import BudgetManager
    bm = BudgetManager()
    state = await bm.get_state(db)
    if state == "blocked":
        budget_fits = False
    budget_status = await bm.get_status(db)
    budget_remaining = budget_status.daily_hard_limit - budget_status.daily_spend
except Exception as e:
    budget_fits = False
    blocks.append(f"Budget check failed: {e}. Cannot proceed without budget verification.")
```

### 4. CLI Session Tracking

**File**: `backend/app/services/model_router.py` (or wherever `_try_cli_route` lives)

Create WorkerSession when CLI execution starts, close in `finally`:

```python
session = WorkerSession(
    worker_id="cli-local",
    task_id=task_id,
    status="running",
)
db.add(session)
await db.flush()

try:
    result = await execute_cli(...)
    session.status = "completed"
    session.exit_code = 0
except Exception:
    session.status = "error"
    session.exit_code = 1
finally:
    # GUARANTEED: session always closed, even on timeout/cancel/exception
    session.updated_at = datetime.now(timezone.utc)
    await db.flush()
```

### 5. Data Retention

**File**: `backend/app/models.py` — new models

```python
class RunEventArchive(Base):
    __tablename__ = "run_event_archives"
    # Same schema as RunEvent
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)

class DailyStats(Base):
    __tablename__ = "daily_stats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    total_runs: Mapped[int] = mapped_column(default=0)
    failed_runs: Mapped[int] = mapped_column(default=0)
    avg_duration_seconds: Mapped[float] = mapped_column(default=0.0)
    active_cli_sessions: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
```

**File**: `backend/app/main.py` — new background tasks

```python
async def _archive_old_events() -> None:
    """Move RunEvents older than 30 days to archive table."""
    while True:
        await asyncio.sleep(86400)  # daily
        try:
            async with async_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                # Select old events
                old = await db.execute(
                    select(RunEvent).where(RunEvent.created_at < cutoff).limit(500)
                )
                events = old.scalars().all()
                for e in events:
                    archive = RunEventArchive(...)
                    db.add(archive)
                    await db.delete(e)
                if events:
                    await db.commit()
        except Exception:
            pass

async def _snapshot_daily_stats() -> None:
    """Write daily statistics snapshot."""
    while True:
        await asyncio.sleep(86400)  # daily
        try:
            # ... compute and write DailyStats ...
        except Exception:
            pass
```

### 6. Proposal Decision Log

**File**: `backend/app/models.py` — add column to ImprovementProposal

```python
decision_log: Mapped[str | None] = mapped_column(Text, nullable=True)
# JSON array of {"action": "approve|reject|archive", "reviewer": "...", "reason": "...", "timestamp": "..."}
```

**File**: `backend/app/services/rd_manager.py` — log decisions

Each of `approve_proposal()`, `reject_proposal()`, `archive_proposal()` appends to the decision_log:

```python
log = json.loads(proposal.decision_log or "[]")
log.append({
    "action": "approved",
    "reviewer": reviewer,
    "reason": notes,
    "timestamp": datetime.now(timezone.utc).isoformat(),
})
proposal.decision_log = json.dumps(log)
```

### 7. Minimal Observability

**File**: `backend/app/api/runs.py` (or new `backend/app/api/system.py`)

```python
@router.get("/api/system/stats")
async def system_stats(db: AsyncSession = Depends(get_db)):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Today's live stats
    total = await db.execute(
        select(func.count()).select_from(Run).where(Run.created_at >= today_start)
    )
    failed = await db.execute(
        select(func.count()).select_from(Run).where(
            Run.created_at >= today_start, Run.status == "failed"
        )
    )
    avg_dur = await db.execute(
        select(func.avg(Run.duration_seconds)).where(
            Run.created_at >= today_start, Run.duration_seconds.isnot(None)
        )
    )
    active_cli = await db.execute(
        select(func.count()).select_from(WorkerSession).where(
            WorkerSession.status == "running"
        )
    )
    event_count = await db.execute(
        select(func.count()).select_from(RunEvent)
    )

    total_runs = total.scalar() or 0
    failed_runs = failed.scalar() or 0

    return {
        "date": today,
        "total_runs_today": total_runs,
        "failed_runs_today": failed_runs,
        "failure_rate_today": round(failed_runs / total_runs, 3) if total_runs else 0.0,
        "avg_duration_seconds_today": round(avg_dur.scalar() or 0.0, 2),
        "active_cli_sessions": active_cli.scalar() or 0,
        "total_event_count": event_count.scalar() or 0,
    }
```

## Files Changed

| File | Change |
|------|--------|
| `backend/app/api/runs.py` | Add pagination (limit/offset) to 4 list endpoints |
| `backend/app/services/run_manager.py` | Fix N+1 in `get_goal_progress()` |
| `backend/app/services/rd_manager.py` | Default dev_mode to false, remove silent budget fallback, add decision logging |
| `backend/app/services/model_router.py` | Create/update WorkerSession for CLI executions |
| `backend/app/models.py` | Add `RunEventArchive`, `DailyStats`, `decision_log` on ImprovementProposal |
| `backend/app/main.py` | Add archive and stats background tasks |
| `backend/app/api/system.py` | New file: `/api/system/stats` endpoint |

## Future Work (Documented, Not Implemented)

- **coordination_service.py N+1**: Queries inside dependency resolution loop. Not touched in this phase — dedicated performance refactor needed.
- **Cursor-based pagination**: Current offset pagination works for ORKA scale. If runs exceed 10K, consider cursor-based.
- **Full observability stack**: Prometheus + Grafana for production monitoring.
- **Worker process implementation**: Actual workers that use the WorkerSession API.

## Acceptance Criteria

- [ ] All 4 runs/events list endpoints accept `limit`/`offset` with defaults (50/0), hard cap at 200 (422 on exceed)
- [ ] `get_goal_progress()` uses a single batch query, not per-task loops
- [ ] `ORKA_DEV_MODE` defaults to `"false"` — production-safe without config
- [ ] Budget check failure produces a block, not a silent pass
- [ ] CLI executions create WorkerSession with `finally`-guaranteed cleanup on success/failure/timeout/exception
- [ ] RunEvents older than 30 days are archived to `run_event_archives`
- [ ] `run_event_archives` is NOT queried by default — only by ResearchAnalyzer or explicit historical queries
- [ ] `DailyStats` snapshots are written by background task
- [ ] `/api/system/stats` returns today's metrics
- [ ] Proposal decisions are logged in `decision_log` column
- [ ] All Phase 1-5 regression tests still pass
- [ ] No new API models or frontend changes required (except `system.py` endpoint)
