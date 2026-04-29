# Phase 6B: Controlled Auto Execution

**Status:** Draft
**Builds on:** Phase 6A (Feedback / Retry / Learning)
**Date:** 2026-04-30

---

## Goal

Allow ORKA to execute approved, low-risk improvement proposals automatically — but only under strict safety controls with full explainability. No uncontrolled loops, no silent paid API fallback, no scheduler.

---

## Architecture

```
POST /api/auto/execute?dry_run=true
         │
         ▼
    ┌─────────────┐
    │ AutoExecutor │──► finds eligible proposals
    └──────┬──────┘
           │ each candidate
           ▼
    ┌──────────────┐
    │ SafetyEngine  │──► 5 gates, returns pass/skip(reason)
    └──────┬───────┘
           │ pass
           ▼
    RDManager.convert_to_goal()
           │
           ▼
    proposal.auto_executed = true
```

Three new files. Two modified files. Zero new loops or background tasks.

---

## 1. AutoExecutor

**File:** `backend/app/services/auto_executor.py`

Responsibilities:
- Query proposals where `status=approved`, `auto_execution_eligible=true`, `auto_executed=false`
- Run each candidate through `SafetyEngine`
- For passing candidates: call `RDManager.convert_to_goal()` (reuses existing flow — no direct code execution)
- For blocked candidates: set `auto_execution_skip_reason` on the proposal
- Return structured result: `{executed: [...], skipped: [{proposal_id, reason}], dry_run: bool}`

Key constraint: AutoExecutor does **not** execute arbitrary code. It only triggers the existing `convert_to_goal` pipeline which creates Goals and Tasks through `CoordinationService`.

---

## 2. SafetyEngine

**File:** `backend/app/services/safety_engine.py`

Five gates, evaluated in order. First failure short-circuits.

### Gate 1: Approval
- Proposal `status` must be `approved`
- `guard_confirmed` must be `true` on the proposal record
- `auto_execution_eligible` must be `true`

### Gate 2: Budget
- Reuse existing `BudgetManager.get_state(db)`
- If state is `blocked` → skip with reason `"budget_blocked"`
- If state is `throttled` → skip with reason `"budget_throttled"`

### Gate 3: Velocity
- Max **1** auto-execution per hour (across all proposals)
- Check: query `ActivityLog` for `action="auto_executed"` events in the last 60 minutes
- If count >= 1 → skip with reason `"velocity_limit"`

### Gate 4: Duplicate
- Same proposal `title` cannot auto-execute twice within 24 hours
- Check: query `ActivityLog` for `action="auto_executed"` with matching title in last 24 hours
- If found → skip with reason `"duplicate_execution"`

### Gate 5: Failure rate
- Look at the last 10 auto-execution results via `ActivityLog` (`action="auto_executed"` or `action="auto_execution_failed"`)
- If failure rate > 50% (i.e., >5 of last 10 failed) → skip with reason `"high_failure_rate"`

All gates return `SafetyResult(passed=bool, gate=str, reason=str)`.

---

## 3. Dry-run Mode

`POST /api/auto/execute?dry_run=true` runs all gates but writes **nothing** to the database. Returns the same structure showing what would execute and what would be skipped.

Implementation: AutoExecutor accepts `dry_run=True` parameter. When set, it skips `db.flush()` / `db.commit()` and returns the plan.

---

## 4. API Endpoints

**File:** `backend/app/api/auto.py`

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/auto/proposals/{id}/eligible` | POST | Mark a proposal as auto-execution eligible |
| `/api/auto/execute` | POST | Execute all eligible proposals (supports `?dry_run=true`) |
| `/api/auto/status` | GET | Return current auto-execution state (last run, velocity count, failure rate) |

### POST /api/auto/proposals/{id}/eligible

Request body:
```json
{ "eligible": true }
```

Constraints:
- Proposal must be `status=approved`
- Proposal must have `guard_confirmed=true` (persisted from approval)
- If proposal `risk_level` is `high` or `critical` → reject with 422

Response: updated `ImprovementProposalResponse`

### POST /api/auto/execute

Query param: `dry_run` (default false)

Response:
```json
{
  "dry_run": true,
  "executed": [],
  "skipped": [
    {"proposal_id": "...", "title": "...", "reason": "velocity_limit"}
  ],
  "timestamp": "2026-04-30T..."
}
```

### GET /api/auto/status

Response:
```json
{
  "eligible_count": 3,
  "last_auto_execution": "2026-04-30T10:00:00Z",
  "velocity_remaining": 1,
  "recent_failure_rate": 0.2,
  "gates": {
    "budget": "normal",
    "velocity": "available",
    "duplicate": "clear",
    "failure_rate": "acceptable"
  }
}
```

---

## 5. Data Model Changes

**Modified:** `backend/app/models.py` — `ImprovementProposal` class

Four additive fields (all nullable with defaults for zero-downtime migration):

```python
# Phase 6B: Auto-execution
guard_confirmed: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False,
)
auto_execution_eligible: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False,
)
auto_executed: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False,
)
auto_executed_at: Mapped[datetime | None] = mapped_column(nullable=True)
auto_execution_skip_reason: Mapped[str | None] = mapped_column(
    String(200), nullable=True,
)
```

Note: `guard_confirmed` is promoted from a runtime parameter to a persisted field. The existing `approve_proposal()` method in `RDManager` will set `proposal.guard_confirmed = guard_confirmed` when called. Existing approved proposals will have `guard_confirmed=false` until re-approved or manually updated.

**Modified:** `backend/app/schemas.py` — add new response schemas

```python
class AutoEligibleRequest(BaseModel):
    eligible: bool

class AutoExecuteResponse(BaseModel):
    dry_run: bool
    executed: list[dict]  # [{proposal_id, title, goal_id}]
    skipped: list[dict]   # [{proposal_id, title, reason}]
    timestamp: datetime

class AutoStatusResponse(BaseModel):
    eligible_count: int
    last_auto_execution: datetime | None
    velocity_remaining: int
    recent_failure_rate: float
    gates: dict
```

Update `ImprovementProposalResponse` to include the five new fields.

---

## 6. Files to Create / Modify

### New files (3)

| File | Purpose |
|---|---|
| `backend/app/services/auto_executor.py` | AutoExecutor service |
| `backend/app/services/safety_engine.py` | SafetyEngine with 5 gates |
| `tests/test_phase6b_auto_execution.py` | All tests |

### Modified files (3)

| File | Change |
|---|---|
| `backend/app/models.py` | Add 5 fields to `ImprovementProposal` |
| `backend/app/schemas.py` | Add 3 response models + update `ImprovementProposalResponse` |
| `backend/app/main.py` | Register `auto` router |

---

## Implementation Plan

### Step 1: Data model + migration
- Add 5 fields to `ImprovementProposal` in `models.py`
- SQLite auto-creates columns via Alembic or app startup (verify existing migration pattern)
- Update `ImprovementProposalResponse` in `schemas.py` with new fields
- Add `AutoEligibleRequest`, `AutoExecuteResponse`, `AutoStatusResponse` schemas

### Step 2: SafetyEngine
- Create `safety_engine.py`
- Implement `SafetyResult` dataclass
- Implement `SafetyEngine.evaluate(proposal, db) -> SafetyResult`
- Each gate queries the DB as needed
- Velocity gate: count `ActivityLog` entries with `action="auto_executed"` in last 60 min
- Duplicate gate: count same-title auto-executions in last 24h via `ActivityLog`
- Failure rate gate: count last 10 auto-execution results from `ActivityLog`

### Step 3: AutoExecutor
- Create `auto_executor.py`
- `AutoExecutor.find_eligible(db) -> list[ImprovementProposal]`
- `AutoExecutor.execute(db, dry_run=False) -> AutoExecuteResult`
- For each eligible proposal: run through SafetyEngine
- If passed and not dry_run: call `RDManager().convert_to_goal(proposal.id, db)`, set `auto_executed=true`, log activity
- If blocked: set `auto_execution_skip_reason`, log activity

### Step 4: API endpoints
- Create `api/auto.py` with 3 endpoints
- Register router in `main.py`
- `POST /api/auto/proposals/{id}/eligible`: validate status, risk level, set flag
- `POST /api/auto/execute`: instantiate AutoExecutor, call execute, return result
- `GET /api/auto/status`: query eligible count, velocity state, failure rate

### Step 5: Wire guard_confirmed persistence
- In `RDManager.approve_proposal()`: set `proposal.guard_confirmed = guard_confirmed`
- This is a one-line additive change — no behavior change for existing calls

### Step 6: Tests
- Create `tests/test_phase6b_auto_execution.py`
- Follow existing test pattern: standalone script, `check()` function, `MockRun` style mocks
- Test cases (see acceptance criteria below)

---

## Acceptance Criteria

### Functional

- [ ] Approved + guard_confirmed + eligible proposal executes via `convert_to_goal`
- [ ] Unapproved proposal is blocked by approval gate
- [ ] Proposal with `guard_confirmed=false` is blocked
- [ ] Proposal with `auto_execution_eligible=false` is not picked up
- [ ] `dry_run=true` returns plan but writes nothing to DB
- [ ] Duplicate title blocked within 24h window
- [ ] Velocity gate blocks second execution within 1 hour
- [ ] Failure rate gate blocks when >50% of last 10 auto-executions failed
- [ ] Budget blocked/throttled proposals are skipped
- [ ] High/critical risk proposals cannot be marked eligible (422)
- [ ] `auto_execution_skip_reason` is set for every skipped proposal

### Safety

- [ ] No direct code execution — all paths go through `RDManager.convert_to_goal()`
- [ ] No silent paid API fallback — budget gate blocks explicitly
- [ ] No background loops or schedulers — execution is request-triggered only
- [ ] Every auto-execution logged in `ActivityLog` with `action="auto_executed"` or `action="auto_execution_failed"`
- [ ] `decision_log` on proposal updated with auto-execution details

### Data integrity

- [ ] New fields default-safe (booleans default false, datetimes nullable)
- [ ] Existing proposals unaffected (all new flags default to false/off)
- [ ] `guard_confirmed` persistence doesn't break existing approval flow

### API

- [ ] `POST /api/auto/proposals/{id}/eligible` returns 404 for missing proposal
- [ ] `POST /api/auto/proposals/{id}/eligible` returns 422 for high/critical risk
- [ ] `POST /api/auto/proposals/{id}/eligible` returns 422 for non-approved status
- [ ] `GET /api/auto/status` returns current gate states
- [ ] `POST /api/auto/execute` returns empty lists when no eligible proposals exist
