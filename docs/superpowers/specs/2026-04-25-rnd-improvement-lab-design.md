# Phase 4: R&D / Improvement Lab — Design Spec

Date: 2026-04-25
Status: Draft
Scope: Phase 4
Depends on: Phase 3C (Goal/Run Management)

## Summary

Turn ORKA from a task execution engine into a self-improving system. Introduce an R&D layer that analyzes past runs, failures, and performance data to generate ImprovementProposals. Users review proposals, approve what makes sense, and approved proposals convert to implementation tasks that execute through the existing Goal/Run pipeline.

**Nothing runs without human approval. No automatic code modification. No uncontrolled agent spawning.**

## Architecture

### Hierarchy

```
Project (existing)
├── Goal (existing, type now matters)
│   │   type = "execution" | "research" | "improvement"
│   │
│   ├── Task (existing)
│   └── Run (existing, feeds analysis)
│
└── ImprovementProposal (new)
    ├── source_goal_id → Goal (what triggered analysis)
    ├── status enum (strict):
    │   draft → under_review → approved → converted_to_goal
    │                       └→ rejected → archived
    ├── evidence links:
    │   related_run_ids, related_goal_ids, related_task_ids
    │   related_agent_type, related_provider, related_model
    ├── proposal (problem, solution, impact, risk)
    ├── approval_guard (quota impact, risk assessment, affected systems)
    └── implementation_goal_id → Goal (created on conversion)
```

### Principle: Extend, Don't Replace

- `Goal.type` already has "execution", "research", "improvement" — just start using them
- `Goal.source_goal_id` already exists for R&D traceability
- `ImprovementProposal` is the only new model
- All execution goes through existing Task → Run → RunEvent pipeline
- No new agent types. Existing agents handle implementation tasks.

## Components

### 1. ImprovementProposal Model

**File**: `backend/app/models.py` (additive)

```python
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

    # ── Status (strict enum) ──
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True,
    )
    # "draft" | "under_review" | "approved" | "rejected"
    # "converted_to_goal" | "archived"

    # ── Problem analysis ──
    problem_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Human-readable summary of the evidence

    # ── Proposed solution ──
    suggested_solution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_impact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    # "low" | "medium" | "high" | "critical"
    implementation_effort: Mapped[str] = mapped_column(String(20), nullable=False, default="moderate")
    # "trivial" | "simple" | "moderate" | "complex" | "major"

    # ── Evidence linking (first-class fields) ──
    related_run_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON array of run IDs that contributed to this finding
    related_goal_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON array of goal IDs involved in the evidence
    related_task_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON array of task IDs involved in the evidence
    related_agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Primary agent type implicated (null if multi-agent)
    related_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Provider implicated, if applicable
    related_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Model implicated, if applicable

    # ── Metadata ──
    analysis_type: Mapped[str] = mapped_column(String(30), nullable=False, default="failure_pattern")
    # "failure_pattern" | "performance_degradation" | "cost_optimization"
    # "quality_improvement" | "architectural" | "manual"
    affected_agents: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON array of agent types affected by the proposed change
    affected_areas: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON array of code/system areas affected

    # ── Approval safety guard ──
    guard_quota_impact: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON: {estimated_runs, estimated_cost, requires_paid_provider, budget_impact}
    guard_risk_assessment: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # JSON: {risk_level, affected_systems, rollback_plan, breaking_changes}
    guard_approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    guard_approved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # ── Review flow ──
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # ── Implementation link ──
    implementation_goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
```

#### Status Transitions (Strict)

```
draft ──propose()──> under_review
under_review ──approve()──> approved
under_review ──reject()──> rejected
approved ──convert()──> converted_to_goal
rejected ──archive()──> archived
draft ──archive()──> archived

INVALID transitions raise ValueError:
  - draft → approved (must go through under_review)
  - under_review → converted_to_goal (must go through approved)
  - approved → rejected (already approved)
  - rejected → approved (cannot re-approve)
  - converted_to_goal → any (terminal state)
```

#### Evidence Linking

Each proposal carries first-class links to the data that triggered it:

| Field | Type | Purpose |
|-------|------|---------|
| `related_run_ids` | JSON array | Specific Run records showing the failure/pattern |
| `related_goal_ids` | JSON array | Goals whose execution revealed the problem |
| `related_task_ids` | JSON array | Tasks that failed or were slow |
| `related_agent_type` | String or null | Primary agent implicated (null = multi-agent) |
| `related_provider` | String or null | Provider involved (e.g., "claude_code", "openai") |
| `related_model` | String or null | Model involved (e.g., "claude-sonnet-4-6") |

Evidence is populated by `ProposalGenerator` from `AnalysisFinding.evidence` at creation time and never modified afterward.

#### Critical Action Guard

Before any proposal converts to a Goal with Tasks, `RDManager` runs a safety check that:

1. **Estimates quota impact** — How many additional Runs will this create? What providers will be used? Will it exceed current quota?
2. **Estimates cost** — Based on task count × provider cost, what's the expected spend?
3. **Assesses risk** — What systems are affected? Are there breaking changes? Is there a rollback plan?
4. **Checks budget** — Will the implementation fit within daily/monthly budget limits?

The guard result is stored in `guard_quota_impact` and `guard_risk_assessment` before the user sees the approval prompt. The frontend displays the guard result and requires **explicit confirmation** before proceeding.

```python
@dataclass
class ApprovalGuard:
    """Safety check run before proposal → Goal conversion."""

    # Quota impact
    estimated_runs: int           # Number of Runs implementation will create
    estimated_cost_usd: float     # Projected cost of implementation runs
    requires_paid_provider: bool  # Will this need a paid API provider?
    budget_remaining_usd: float   # Current budget headroom
    budget_fits: bool             # Does estimated_cost fit in remaining budget?

    # Risk assessment
    risk_level: str               # "low" | "medium" | "high" | "critical"
    affected_systems: list[str]   # Systems/components that will be touched
    has_breaking_changes: bool    # Could this break existing functionality?
    rollback_possible: bool       # Can changes be reverted?
    rollback_plan: str            # How to revert if things go wrong

    # Decision
    can_proceed: bool             # True only if budget_fits AND not critical without explicit override
    warnings: list[str]           # Non-blocking warnings to show user
    blocks: list[str]             # Blocking issues that prevent conversion
```

### 2. ResearchAnalyzer Service

**File**: `backend/app/services/research_analyzer.py` (new)

The analysis engine. Scans Runs, failures, and performance data to find improvement opportunities.

```python
class ResearchAnalyzer:
    """Analyzes project data to identify improvement opportunities."""

    async def analyze_project(
        self, project_id: str, db: AsyncSession
    ) -> list[AnalysisFinding]:
        """Full project analysis. Returns prioritized findings."""
        ...

    async def analyze_failures(
        self, project_id: str, db: AsyncSession
    ) -> list[AnalysisFinding]:
        """Find failure patterns: repeated errors, same failure_type, retry storms."""
        ...

    async def analyze_performance(
        self, project_id: str, db: AsyncSession
    ) -> list[AnalysisFinding]:
        """Find performance gaps: slow agents, high retry rates, quota blocks."""
        ...

    async def analyze_costs(
        self, project_id: str, db: AsyncSession
    ) -> list[AnalysisFinding]:
        """Find cost optimization opportunities: over-provisioned tiers, wasted quota."""
        ...
```

**AnalysisFinding** (internal, not persisted):

```python
@dataclass
class AnalysisFinding:
    finding_type: str       # "failure_pattern" | "performance_gap" | "cost_waste"
    severity: str           # "low" | "medium" | "high" | "critical"
    title: str
    description: str
    evidence: list[dict]    # [{run_id, task_id, goal_id, error, timestamp}, ...]
    affected_agents: list[str]
    suggested_fix: str
    expected_impact: str
    risk_level: str
    effort: str             # "trivial" | "simple" | "moderate" | "complex"

    # Evidence linking
    related_run_ids: list[str]
    related_goal_ids: list[str]
    related_task_ids: list[str]
    related_agent_type: str | None = None
    related_provider: str | None = None
    related_model: str | None = None
```

**Analysis strategies:**

| Strategy | What it looks for | Example finding |
|----------|-------------------|-----------------|
| **Failure pattern** | Same `failure_type` across 3+ runs | "Backend agent: 8 timeout failures in 24h on code_gen tasks" |
| **Retry storm** | High `retry_count` per task | "Task X retried 5 times — quota_block suggests provider issue" |
| **Slow execution** | `duration_seconds` > 2x average | "QA agent avg 45s vs system avg 12s" |
| **Cost waste** | High-cost tier for low-complexity tasks | "High-tier model used for 12 simple doc tasks ($2.40 waste)" |
| **Quota exhaustion** | Repeated `blocked` runs | "CLI provider blocked 6 times — needs quota increase or API fallback" |
| **Agent bottleneck** | One agent type has 90% of failures | "Frontend agent: 67% failure rate vs 8% system average" |

### 3. ProposalGenerator Service

**File**: `backend/app/services/proposal_generator.py` (new)

Converts analysis findings into ImprovementProposals. Follows the SpawnPlanGenerator pattern.

```python
class ProposalGenerator:
    """Converts analysis findings into structured improvement proposals."""

    async def generate_from_analysis(
        self,
        project_id: str,
        findings: list[AnalysisFinding],
        source_goal_id: str | None = None,
        db: AsyncSession = None,
    ) -> list[ImprovementProposal]:
        """Generate proposals from analysis findings."""
        ...

    async def generate_from_goal(
        self,
        goal_id: str,
        db: AsyncSession,
    ) -> list[ImprovementProposal]:
        """Analyze a specific goal's runs and generate proposals."""
        ...

    def _prioritize_findings(
        self, findings: list[AnalysisFinding]
    ) -> list[AnalysisFinding]:
        """Sort by severity × frequency × impact."""
        ...
```

**Prioritization formula:**

```
score = severity_weight × occurrence_count × (1 + affected_agent_count)
severity_weight: critical=4, high=3, medium=2, low=1
```

### 4. RDManager Service

**File**: `backend/app/services/rd_manager.py` (new)

Orchestrates the full R&D flow. The main entry point.

```python
class RDManager:
    """Orchestrates the R&D / Improvement Lab workflow."""

    # ── Allowed status transitions ──
    _TRANSITIONS = {
        "draft": {"under_review", "archived"},
        "under_review": {"approved", "rejected"},
        "approved": {"converted_to_goal"},
        "rejected": {"archived"},
        "converted_to_goal": set(),   # terminal
        "archived": set(),            # terminal
    }

    def _validate_transition(self, current: str, target: str) -> None:
        allowed = self._TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid transition: {current} → {target}. "
                f"Allowed: {allowed or 'none (terminal state)'}"
            )

    async def submit_to_research(
        self,
        project_id: str,
        goal_id: str | None = None,
        analysis_types: list[str] | None = None,
        db: AsyncSession = None,
    ) -> list[ImprovementProposal]:
        """Step 1: Analyze and generate proposals. Returns draft proposals."""
        ...

    async def submit_for_review(
        self, proposal_id: str, db: AsyncSession
    ) -> ImprovementProposal:
        """Step 2: Move draft → under_review (ready for review)."""
        self._validate_transition(proposal.status, "under_review")
        ...

    async def run_approval_guard(
        self, proposal_id: str, db: AsyncSession
    ) -> ApprovalGuard:
        """Step 3a: Run Critical Action Guard. Returns safety assessment.
        Does NOT modify the proposal. Caller must show result to user
        and get explicit confirmation before calling approve_proposal()."""
        ...

    async def approve_proposal(
        self,
        proposal_id: str,
        reviewer: str = "user",
        notes: str | None = None,
        guard_confirmed: bool = False,
        db: AsyncSession = None,
    ) -> ImprovementProposal:
        """Step 3b: Approve proposal. Must have guard_confirmed=True.
        Sets status to 'approved'. Does NOT create Goal yet.
        Raises ValueError if guard_confirmed is False."""
        self._validate_transition(proposal.status, "approved")
        if not guard_confirmed:
            raise ValueError("Approval requires guard_confirmed=True. Run run_approval_guard() first.")
        ...

    async def convert_to_goal(
        self,
        proposal_id: str,
        db: AsyncSession,
    ) -> tuple[ImprovementProposal, Goal]:
        """Step 4: Convert approved proposal to implementation Goal + Tasks.
        Sets status to 'converted_to_goal'. Creates Goal(type="improvement")
        with implementation Tasks via CoordinationService.
        Returns (proposal, implementation_goal)."""
        self._validate_transition(proposal.status, "converted_to_goal")
        ...

    async def reject_proposal(
        self,
        proposal_id: str,
        reviewer: str = "user",
        reason: str | None = None,
        db: AsyncSession = None,
    ) -> ImprovementProposal:
        """Reject proposal. Moves to 'rejected' status."""
        self._validate_transition(proposal.status, "rejected")
        ...

    async def archive_proposal(
        self, proposal_id: str, db: AsyncSession
    ) -> ImprovementProposal:
        """Archive a draft or rejected proposal."""
        self._validate_transition(proposal.status, "archived")
        ...

    async def get_project_proposals(
        self, project_id: str, status: str | None = None, db: AsyncSession = None,
    ) -> list[ImprovementProposal]:
        """List proposals for a project, optionally filtered by status."""
        ...
```

### 5. API Schemas

**File**: `backend/app/schemas.py` (additive)

```python
class AnalysisRequest(BaseModel):
    project_id: str
    goal_id: str | None = None
    analysis_types: list[str] | None = None
    # ["failure_pattern", "performance_degradation", "cost_optimization", "quality_improvement"]

class ProposalReview(BaseModel):
    reviewer: str = "user"
    notes: str | None = None

class GuardConfirm(BaseModel):
    reviewer: str = "user"
    notes: str | None = None
    guard_confirmed: bool = False  # Must be explicitly set to True

class ImprovementProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    source_goal_id: str | None = None
    title: str
    status: str
    problem_description: str
    evidence_summary: str
    suggested_solution: str
    expected_impact: str
    risk_level: str
    implementation_effort: str
    analysis_type: str
    affected_agents: str
    affected_areas: str

    # Evidence linking
    related_run_ids: str
    related_goal_ids: str
    related_task_ids: str
    related_agent_type: str | None = None
    related_provider: str | None = None
    related_model: str | None = None

    # Guard
    guard_quota_impact: str
    guard_risk_assessment: str
    guard_approved_by: str | None = None
    guard_approved_at: datetime | None = None

    # Review
    reviewed_by: str | None = None
    review_notes: str | None = None
    reviewed_at: datetime | None = None
    implementation_goal_id: str | None = None
    created_at: datetime
    updated_at: datetime

class ApprovalGuardResponse(BaseModel):
    estimated_runs: int
    estimated_cost_usd: float
    requires_paid_provider: bool
    budget_remaining_usd: float
    budget_fits: bool
    risk_level: str
    affected_systems: list[str]
    has_breaking_changes: bool
    rollback_possible: bool
    rollback_plan: str
    can_proceed: bool
    warnings: list[str]
    blocks: list[str]

class ProposalConversionResponse(BaseModel):
    proposal: ImprovementProposalResponse
    implementation_goal: GoalResponse
    tasks_created: int
```

### 6. API Endpoints

**File**: `backend/app/api/research.py` (new)

```
# Analysis & Proposal Generation
POST   /api/projects/{id}/research/analyze
       → Analyze project, return draft proposals

POST   /api/goals/{id}/research/analyze
       → Analyze a specific goal's runs, return draft proposals

# Proposal Management
GET    /api/projects/{id}/proposals?status=under_review
       → List proposals for project, optionally filtered by status

GET    /api/proposals/{id}
       → Get proposal detail with evidence links

PATCH  /api/proposals/{id}/submit
       → Move draft → under_review (ready for review)

GET    /api/proposals/{id}/guard
       → Run Critical Action Guard, return safety assessment
       → Does NOT modify proposal. Frontend shows result to user.

PATCH  /api/proposals/{id}/approve
       → Approve with guard_confirmed=True.
       → Body: {guard_confirmed: true, reviewer, notes}
       → Sets status to 'approved'. Does NOT create Goal.

PATCH  /api/proposals/{id}/convert
       → Convert approved proposal → Goal + Tasks.
       → Sets status to 'converted_to_goal'.
       → Returns {proposal, implementation_goal, tasks_created}.

PATCH  /api/proposals/{id}/reject
       → Reject with reason. Sets status to 'rejected'.

PATCH  /api/proposals/{id}/archive
       → Archive draft or rejected proposal.

GET    /api/projects/{id}/proposals/summary
       → Summary: counts by status, top risk areas, evidence stats
```

## Flow Diagrams

### Flow 1: User-Initiated R&D

```
User                    ORKA API              ResearchAnalyzer        ProposalGenerator
 │                         │                        │                       │
 │  POST /research/analyze │                        │                       │
 │────────────────────────>│                        │                       │
 │                         │  analyze_project()     │                       │
 │                         │───────────────────────>│                       │
 │                         │                        │  Query Runs           │
 │                         │                        │──┐                    │
 │                         │                        │<─┘                    │
 │                         │                        │  Query RunEvents      │
 │                         │                        │──┐                    │
 │                         │                        │<─┘                    │
 │                         │                        │  Query UsageRecords   │
 │                         │                        │──┐                    │
 │                         │                        │<─┘                    │
 │                         │  findings[]            │                       │
 │                         │<───────────────────────│                       │
 │                         │                        │                       │
 │                         │  generate_from_analysis()                      │
 │                         │───────────────────────────────────────────────>│
 │                         │                        │   create proposals    │
 │                         │                        │──┐                    │
 │                         │  proposals[]           │<─┘                    │
 │                         │<───────────────────────────────────────────────│
 │  draft proposals        │                        │                       │
 │<────────────────────────│                        │                       │
```

### Flow 2: Proposal Review, Guard & Conversion

```
User                    ORKA API              RDManager              CoordinationService
 │                         │                        │                       │
 │  PATCH /submit          │                        │                       │
 │  (draft→under_review)   │                        │                       │
 │────────────────────────>│                        │                       │
 │                         │  submit_for_review()   │                       │
 │                         │───────────────────────>│                       │
 │                         │  validate transition   │                       │
 │                         │──┐                     │                       │
 │                         │<─┘                     │                       │
 │  {status: under_review} │                        │                       │
 │<────────────────────────│                        │                       │
 │                         │                        │                       │
 │  GET /guard             │                        │                       │
 │────────────────────────>│                        │                       │
 │                         │  run_approval_guard()  │                       │
 │                         │───────────────────────>│                       │
 │                         │                        │  Check budget          │
 │                         │                        │──┐                     │
 │                         │                        │<─┘                     │
 │                         │                        │  Estimate runs/cost    │
 │                         │                        │──┐                     │
 │                         │                        │<─┘                     │
 │                         │                        │  Assess risk           │
 │                         │                        │──┐                     │
 │                         │                        │<─┘                     │
 │  {guard result shown}   │                        │                       │
 │<────────────────────────│                        │                       │
 │                         │                        │                       │
 │  (User reviews guard, confirms)                  │                       │
 │                         │                        │                       │
 │  PATCH /approve         │                        │                       │
 │  {guard_confirmed:true} │                        │                       │
 │────────────────────────>│                        │                       │
 │                         │  approve_proposal()    │                       │
 │                         │───────────────────────>│                       │
 │                         │  validate transition   │                       │
 │                         │  check guard_confirmed │                       │
 │                         │──┐                     │                       │
 │                         │<─┘                     │                       │
 │  {status: approved}     │                        │                       │
 │<────────────────────────│                        │                       │
 │                         │                        │                       │
 │  PATCH /convert         │                        │                       │
 │────────────────────────>│                        │                       │
 │                         │  convert_to_goal()     │                       │
 │                         │───────────────────────>│                       │
 │                         │                        │  Create Goal           │
 │                         │                        │  type="improvement"    │
 │                         │                        │──┐                     │
 │                         │                        │<─┘                     │
 │                         │                        │  Create Tasks          │
 │                         │                        │  (via PIPELINE)        │
 │                         │                        │──────────────────────>│
 │                         │                        │  tasks + dependencies │
 │                         │                        │<──────────────────────│
 │                         │                        │                        │
 │  {proposal, goal, N}    │                        │                       │
 │<────────────────────────│                        │                       │
```

### Flow 3: System-Triggered Auto-Analysis (Future)

```
Cron/Scheduler           RDManager              ResearchAnalyzer        ProposalGenerator
 │                         │                        │                       │
 │  check_project_health() │                        │                       │
 │────────────────────────>│                        │                       │
 │                         │  Quick scan:           │                       │
 │                         │  failure_rate > 30%?   │                       │
 │                         │──┐                     │                       │
 │                         │<─┘                     │                       │
 │                         │  YES → full analysis   │                       │
 │                         │───────────────────────>│                       │
 │                         │                        │  (same as Flow 1)      │
 │                         │                        │                       │
 │  (creates DRAFT only)   │                        │                       │
 │<────────────────────────│                        │                       │
 │                         │                        │                       │
 │  (User reviews drafts in dashboard later)        │                       │
```

## Integration with Goal/Run

### Goal.type Usage

| Type | Purpose | Created by |
|------|---------|-----------|
| `execution` | Normal task execution (default) | User via dashboard |
| `research` | Investigative analysis, no code changes | R&D auto-analysis |
| `improvement` | Implement an approved proposal | RDManager.approve_proposal() |

### source_goal_id Traceability

```
User creates Goal A (type="execution", "Build auth system")
├── Tasks execute, Runs created
├── Some Runs fail
│
└── User sends Goal A to R&D
    └── Analysis finds auth token timeout pattern
    └── Proposal: "Increase session timeout, add retry logic"
    └── User approves
    └── RDManager creates Goal B (type="improvement", source_goal_id=A.id)
        ├── Task: "Increase session timeout" → backend agent
        ├── Task: "Add retry logic to auth" → backend agent
        ├── Task: "Test auth resilience" → qa agent
        └── Task: "Update auth docs" → docs agent
```

### RunEvent Integration

New event types for R&D:

| Event type | When |
|-----------|------|
| `analysis_started` | R&D analysis begins for a project/goal |
| `analysis_completed` | Findings generated |
| `proposal_created` | Draft proposal saved |
| `proposal_proposed` | Moved to review-ready state |
| `proposal_approved` | User approves |
| `proposal_rejected` | User rejects |
| `implementation_started` | Tasks created from approved proposal |

These events attach to the research Goal's Run, creating a full audit trail.

## Analysis Strategies (Detail)

### Strategy 1: Failure Pattern Detection

```python
async def analyze_failures(self, project_id: str, db: AsyncSession) -> list[AnalysisFinding]:
    runs = await self._get_project_runs(project_id, db)
    failed = [r for r in runs if r.status == "failed"]

    # Group by failure_type
    by_type: dict[str, list[Run]] = {}
    for r in failed:
        key = r.failure_type or "unknown"
        by_type.setdefault(key, []).append(r)

    findings = []
    for ftype, f_runs in by_type.items():
        if len(f_runs) >= 3:  # Threshold: 3+ failures of same type
            # Extract error patterns
            errors = [r.error_message for r in f_runs[:5] if r.error_message]
            agents = list(set(r.agent_type for r in f_runs))

            findings.append(AnalysisFinding(
                finding_type="failure_pattern",
                severity=self._severity_from_count(len(f_runs)),
                title=f"Repeated {ftype} failures in {', '.join(agents)}",
                description=f"{len(f_runs)} runs failed with {ftype} in this project",
                evidence=[{"run_id": r.id, "error": r.error_message} for r in f_runs[:5]],
                affected_agents=agents,
                suggested_fix=self._suggest_fix(ftype, errors),
                expected_impact=f"Could prevent {len(f_runs)} future failures",
                risk_level="medium",
                effort="moderate",
            ))
    return findings
```

### Strategy 2: Performance Degradation

```python
async def analyze_performance(self, project_id: str, db: AsyncSession) -> list[AnalysisFinding]:
    perf_data = await RunManager().get_agent_performance(project_id, db=db)

    findings = []
    for agent in perf_data:
        # High retry rate
        if agent.retry_rate > 0.15:
            findings.append(AnalysisFinding(
                finding_type="performance_degradation",
                severity="high",
                title=f"{agent.agent_type} agent: {agent.retry_rate:.0%} retry rate",
                description=f"{agent.agent_type} retried {agent.retry_rate:.0%} of runs",
                evidence=[],
                affected_agents=[agent.agent_type],
                suggested_fix="Investigate root cause of retries, add pre-validation",
                expected_impact=f"Could save {int(agent.total_runs * agent.retry_rate)} retry executions",
                risk_level="low",
                effort="simple",
            ))

        # Slow execution
        if agent.avg_duration_seconds > 30:
            findings.append(AnalysisFinding(
                finding_type="performance_degradation",
                severity="medium",
                title=f"{agent.agent_type} agent: avg {agent.avg_duration_seconds:.1f}s execution",
                description=f"Average duration significantly above baseline",
                evidence=[],
                affected_agents=[agent.agent_type],
                suggested_fix="Profile slow operations, consider task decomposition",
                expected_impact="50-70% execution time reduction possible",
                risk_level="medium",
                effort="complex",
            ))
    return findings
```

### Strategy 3: Cost Optimization

```python
async def analyze_costs(self, project_id: str, db: AsyncSession) -> list[AnalysisFinding]:
    # Query UsageRecords for the project
    runs = await self._get_project_runs(project_id, db)
    by_mode = {}
    for r in runs:
        by_mode.setdefault(r.execution_mode, []).append(r)

    findings = []

    # Check if too many tasks use API when CLI is available
    api_runs = by_mode.get("api", [])
    cli_runs = by_mode.get("cli", [])
    if len(api_runs) > 10 and len(cli_runs) == 0:
        findings.append(AnalysisFinding(
            finding_type="cost_optimization",
            severity="low",
            title="All runs use API mode — CLI providers may reduce cost",
            description=f"{len(api_runs)} API runs, 0 CLI runs",
            evidence=[],
            affected_agents=[],
            suggested_fix="Configure CLI providers for code_gen and review tasks",
            expected_impact="CLI runs have $0 marginal cost",
            risk_level="low",
            effort="simple",
        ))
    return findings
```

## Database Indexes

```python
# On ImprovementProposal
index=True on: project_id, status, source_goal_id, implementation_goal_id
```

## What Stays the Same

- All existing models, API endpoints, frontend components
- Phase 1/2/3A/3B/3C behavior completely preserved
- Task → Run → RunEvent pipeline unchanged
- Goal/Run progress calculation unchanged
- Agent simulation and task distribution unchanged
- Budget/quota/routing system unchanged
- Brainstorm system unchanged

## What Gets Removed / Deprecated

Nothing removed. All changes additive.

## New Files Summary

| File | Purpose |
|------|---------|
| `backend/app/services/research_analyzer.py` | Analysis engine: failure patterns, performance, cost |
| `backend/app/services/proposal_generator.py` | Converts findings → ImprovementProposals |
| `backend/app/services/rd_manager.py` | Orchestrates R&D flow |
| `backend/app/api/research.py` | R&D API endpoints |
| `frontend/components/ResearchPanel.tsx` | R&D dashboard: analyze, review, approve |
| `frontend/components/ProposalCard.tsx` | Individual proposal display |
| `tests/test_research_lab.py` | E2E tests for R&D flow |

## Modified Files Summary

| File | Change |
|------|--------|
| `backend/app/models.py` | Add ImprovementProposal model |
| `backend/app/schemas.py` | Add R&D schemas |
| `backend/app/database.py` | Import new model |
| `backend/app/main.py` | Register research router |
| `frontend/lib/types.ts` | Add ImprovementProposal interfaces |
| `frontend/lib/api.ts` | Add research API methods |
| `frontend/app/project/[id]/page.tsx` | Add ResearchPanel section |

## Constraints (Mandatory)

1. **No automatic code modification** — Proposals describe changes; humans approve before any execution
2. **No uncontrolled agent spawning** — Approval creates a Goal with tasks; tasks use normal pipeline
3. **Respect CLI/API quota rules** — Implementation tasks route through ModelRouter like any other task
4. **No silent paid fallback** — Implementation runs follow same budget/quota constraints
5. **Draft-first** — Analysis always creates drafts; user must explicitly submit for review, approve, then convert
6. **Strict status transitions** — Invalid transitions raise ValueError; no skipping steps
7. **Critical Action Guard required** — No approval without running guard first. `guard_confirmed=True` is mandatory.
8. **Evidence traceability** — Every proposal links to specific Runs, Tasks, Goals, agents, providers via first-class fields
9. **Immutable proposals** — Once created, proposal content doesn't change; status transitions only
10. **Full audit trail** — Every R&D action logged as RunEvent on research Goal
11. **Scope boundary** — R&D analyzes and proposes; it never executes code directly
12. **Guard blocks on critical risk** — If guard returns `can_proceed=false`, conversion is blocked until user addresses blocks

## Acceptance Criteria

- [ ] ImprovementProposal model created with all fields (including evidence links and guard fields)
- [ ] Status enum enforced: draft → under_review → approved → converted_to_goal (and rejected/archived branches)
- [ ] Invalid status transitions raise ValueError
- [ ] ResearchAnalyzer detects failure patterns from Run data
- [ ] ResearchAnalyzer detects performance degradation from agent performance data
- [ ] ResearchAnalyzer detects cost optimization opportunities
- [ ] Evidence linking populated: related_run_ids, related_goal_ids, related_task_ids, related_agent_type, related_provider, related_model
- [ ] ProposalGenerator creates structured proposals from findings with evidence links
- [ ] Proposals are prioritized by severity × frequency
- [ ] RDManager.submit_to_research() creates draft proposals
- [ ] RDManager.submit_for_review() moves draft → under_review
- [ ] RDManager.run_approval_guard() returns quota impact + risk assessment without modifying proposal
- [ ] RDManager.approve_proposal() requires guard_confirmed=True
- [ ] RDManager.convert_to_goal() creates Goal (type="improvement") with Tasks
- [ ] Guard blocks conversion when budget exceeded or critical risk
- [ ] source_goal_id traceability works end-to-end
- [ ] All R&D API endpoints work (including /guard)
- [ ] ResearchPanel renders proposals with guard results, approve/reject actions
- [ ] No existing Phase 1-3C behavior broken
- [ ] All constraints enforced
