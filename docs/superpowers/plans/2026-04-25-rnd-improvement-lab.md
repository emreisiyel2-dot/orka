# Phase 4: R&D / Improvement Lab — Implementation Plan

**Goal:** Add ImprovementProposal model, ResearchAnalyzer, ProposalGenerator, RDManager services, API, frontend, and tests — all additive.

**Architecture:** One new model. Three new services. One new API router. Two new frontend components. Strict status transitions. Critical Action Guard before conversion.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy (async), SQLite, Next.js 14, TypeScript

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/services/research_analyzer.py` | Analysis engine: failure patterns, performance, cost |
| `backend/app/services/proposal_generator.py` | Converts findings → ImprovementProposals |
| `backend/app/services/rd_manager.py` | Orchestrates R&D flow with status transitions + guard |
| `backend/app/api/research.py` | R&D API endpoints |
| `frontend/components/ResearchPanel.tsx` | R&D dashboard: analyze, review, approve |
| `frontend/components/ProposalCard.tsx` | Individual proposal with guard display |
| `tests/test_research_lab.py` | E2E tests for R&D flow |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/models.py` | Add ImprovementProposal model |
| `backend/app/schemas.py` | Add R&D schemas + ApprovalGuardResponse |
| `backend/app/database.py` | Import new model |
| `backend/app/main.py` | Register research router |
| `frontend/lib/types.ts` | Add ImprovementProposal + ApprovalGuard interfaces |
| `frontend/lib/api.ts` | Add research API methods |
| `frontend/app/project/[id]/page.tsx` | Add ResearchPanel section |

---

## Step 1: Data Model

### 1.1 Add ImprovementProposal to `backend/app/models.py`

Add after RunEvent model (Phase 3C section). Key fields:

- Status enum: `draft`, `under_review`, `approved`, `rejected`, `converted_to_goal`, `archived`
- Evidence linking: `related_run_ids`, `related_goal_ids`, `related_task_ids`, `related_agent_type`, `related_provider`, `related_model`
- Guard fields: `guard_quota_impact`, `guard_risk_assessment`, `guard_approved_by`, `guard_approved_at`
- Review fields: `reviewed_by`, `review_notes`, `reviewed_at`
- Implementation link: `implementation_goal_id` → Goal FK

### 1.2 Update `backend/app/database.py` imports

Add `ImprovementProposal` to the import line.

---

## Step 2: API Schemas

### 2.1 Add to `backend/app/schemas.py`

- `AnalysisRequest` — project_id, goal_id, analysis_types
- `ProposalReview` — reviewer, notes
- `GuardConfirm` — reviewer, notes, guard_confirmed (must be true)
- `ImprovementProposalResponse` — all fields including evidence links and guard
- `ApprovalGuardResponse` — quota impact + risk assessment + can_proceed
- `ProposalConversionResponse` — proposal + implementation_goal + tasks_created

---

## Step 3: ResearchAnalyzer Service

### 3.1 Create `backend/app/services/research_analyzer.py`

Internal `AnalysisFinding` dataclass with evidence linking fields.

Methods:
- `analyze_project(project_id, db)` → list[AnalysisFinding] — runs all strategies
- `analyze_failures(project_id, db)` → list[AnalysisFinding] — groups failed Runs by failure_type, threshold=3
- `analyze_performance(project_id, db)` → list[AnalysisFinding] — checks retry_rate > 15%, avg_duration > 30s
- `analyze_costs(project_id, db)` → list[AnalysisFinding] — checks API-only usage when CLI available
- `_get_project_runs(project_id, db)` → list[Run] — helper query
- `_severity_from_count(count)` → "low"|"medium"|"high"|"critical"
- `_suggest_fix(failure_type, errors)` → string

Each finding populates: `related_run_ids`, `related_goal_ids`, `related_task_ids`, `related_agent_type`, `related_provider`, `related_model`.

---

## Step 4: ProposalGenerator Service

### 4.1 Create `backend/app/services/proposal_generator.py`

Methods:
- `generate_from_analysis(project_id, findings, source_goal_id, db)` → list[ImprovementProposal]
- `generate_from_goal(goal_id, db)` → list[ImprovementProposal] — scopes analysis to one goal
- `_prioritize_findings(findings)` → sorted list (severity_weight × count × (1 + agent_count))

Populates evidence linking fields from finding data. Creates proposals in `draft` status.

---

## Step 5: RDManager Service

### 5.1 Create `backend/app/services/rd_manager.py`

Status transition map:
```python
_TRANSITIONS = {
    "draft": {"under_review", "archived"},
    "under_review": {"approved", "rejected"},
    "approved": {"converted_to_goal"},
    "rejected": {"archived"},
    "converted_to_goal": set(),
    "archived": set(),
}
```

Methods:
- `_validate_transition(current, target)` — raises ValueError on invalid
- `submit_to_research(project_id, goal_id, analysis_types, db)` → list[ImprovementProposal] — creates drafts
- `submit_for_review(proposal_id, db)` → draft → under_review
- `run_approval_guard(proposal_id, db)` → ApprovalGuard — estimates quota impact, cost, risk, budget fit
- `approve_proposal(proposal_id, reviewer, notes, guard_confirmed, db)` → under_review → approved (requires guard_confirmed=True)
- `convert_to_goal(proposal_id, db)` → approved → converted_to_goal — creates Goal(type="improvement") + Tasks via CoordinationService
- `reject_proposal(proposal_id, reviewer, reason, db)` → under_review → rejected
- `archive_proposal(proposal_id, db)` → draft/rejected → archived
- `get_project_proposals(project_id, status, db)` → list[ImprovementProposal]

Guard implementation:
- Estimates runs from PIPELINE length (4 tasks per conversion)
- Estimates cost from provider cost × run count
- Checks budget via BudgetManager
- Assesses risk from proposal.risk_level + affected_areas
- `can_proceed = budget_fits AND not has_critical_blocks`

---

## Step 6: API Endpoints

### 6.1 Create `backend/app/api/research.py`

| Method | Path | Action |
|--------|------|--------|
| POST | `/api/projects/{id}/research/analyze` | Analyze project → draft proposals |
| POST | `/api/goals/{id}/research/analyze` | Analyze goal → draft proposals |
| GET | `/api/projects/{id}/proposals` | List proposals (optional ?status= filter) |
| GET | `/api/proposals/{id}` | Get proposal detail |
| PATCH | `/api/proposals/{id}/submit` | draft → under_review |
| GET | `/api/proposals/{id}/guard` | Run guard, return assessment |
| PATCH | `/api/proposals/{id}/approve` | under_review → approved (needs guard_confirmed) |
| PATCH | `/api/proposals/{id}/convert` | approved → converted_to_goal (creates Goal+Tasks) |
| PATCH | `/api/proposals/{id}/reject` | under_review → rejected |
| PATCH | `/api/proposals/{id}/archive` | draft/rejected → archived |
| GET | `/api/projects/{id}/proposals/summary` | Counts by status, top risk areas |

### 6.2 Register router in `backend/app/main.py`

---

## Step 7: Frontend

### 7.1 Add TypeScript interfaces to `frontend/lib/types.ts`

- `ImprovementProposal` — all fields including evidence links and guard
- `ApprovalGuard` — quota impact + risk assessment
- `ProposalConversion` — proposal + goal + task count

### 7.2 Add API methods to `frontend/lib/api.ts`

- `analyzeProject`, `analyzeGoal`
- `getProposals`, `getProposal`
- `submitProposal` (draft → under_review)
- `getProposalGuard` (run guard)
- `approveProposal` (with guard_confirmed)
- `convertProposal` (→ Goal+Tasks)
- `rejectProposal`, `archiveProposal`
- `getProposalSummary`

### 7.3 Create `frontend/components/ProposalCard.tsx`

Single proposal display:
- Title, status badge, risk level badge
- Problem description, suggested solution
- Evidence links (clickable Run/Task/Goal IDs)
- Guard result display (when available): estimated cost, risk, warnings, blocks
- Action buttons: Submit / Approve / Convert / Reject / Archive
- Approve button requires guard_confirmed acknowledgment

### 7.4 Create `frontend/components/ResearchPanel.tsx`

R&D dashboard section:
- "Analyze Project" button → triggers analysis
- Proposal list with status filter tabs (All / Draft / Under Review / Approved / Converted)
- Each proposal rendered via ProposalCard
- Summary stats: counts by status, top affected agents

### 7.5 Integrate into `frontend/app/project/[id]/page.tsx`

Add ResearchPanel as a new section below the Goals & Runs section.

---

## Step 8: Tests

### 8.1 Create `tests/test_research_lab.py`

Test cases:
1. **ImprovementProposal CRUD** — create, list, get, status transitions
2. **Status transitions** — valid transitions work, invalid raise ValueError
3. **ResearchAnalyzer** — failure pattern detection, performance analysis, cost analysis
4. **ProposalGenerator** — findings → proposals with evidence links populated
5. **Evidence linking** — related_run_ids, related_goal_ids, related_task_ids correctly set
6. **Approval guard** — returns quota impact + risk assessment, blocks on budget exceeded
7. **Approval requires guard** — approve without guard_confirmed raises error
8. **Convert to goal** — approved proposal creates Goal(type="improvement") + Tasks
9. **source_goal_id traceability** — improvement goal links back to original
10. **No regression** — existing Phase 1-3C endpoints still work

---

## Step 9: Verification Plan

1. Run app, check DB table created (improvement_proposals)
2. Create project with failing runs → analyze → verify draft proposals created
3. Submit for review → verify status transition
4. Run guard → verify quota impact and risk assessment returned
5. Approve with guard_confirmed → verify status = approved
6. Convert → verify Goal + Tasks created with correct type/source_goal_id
7. Frontend: ResearchPanel renders, proposals display with guard info
8. All existing tests still pass
9. Invalid transitions blocked with ValueError

---

## Step 10: Acceptance Criteria

- [ ] ImprovementProposal model with all fields (evidence links + guard)
- [ ] Status enum enforced with transition validation
- [ ] ResearchAnalyzer: failure patterns, performance, cost detection
- [ ] Evidence linking populated from analysis data
- [ ] ProposalGenerator with prioritization
- [ ] RDManager with full lifecycle (analyze→submit→guard→approve→convert)
- [ ] Guard blocks conversion on budget exceeded or critical risk
- [ ] Approval requires guard_confirmed=True
- [ ] All 11 API endpoints working
- [ ] ProposalCard shows evidence links and guard results
- [ ] ResearchPanel with analyze button and status filter
- [ ] No Phase 1-3C regressions
- [ ] All tests pass
