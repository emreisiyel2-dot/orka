# Phase 5: R&D Intelligence Upgrade — Design Spec

Date: 2026-04-25
Status: Draft
Scope: Phase 5
Depends on: Phase 4 (R&D / Improvement Lab)

## Summary

Upgrade the R&D analysis engine from template-based pattern detection to context-aware intelligent reasoning. The current system works structurally but produces generic, noisy output. This phase makes proposals feel like a senior engineer's review — specific, actionable, and prioritized by real impact.

**No new models. No new API endpoints. No new frontend components.** Only upgrade the three services: `ResearchAnalyzer`, `ProposalGenerator`, and `RDManager.run_approval_guard()`.

## Problem Statement

The validation run with 10 runs (4 timeout, 3 quota_block, 3 success) revealed six specific weaknesses:

| # | Problem | Root Cause | Fix |
|---|---------|-----------|-----|
| 1 | QA 50% retry rate from 2 runs | No minimum sample size | Add thresholds |
| 2 | 4 timeout failures = "low" severity | Linear scaling too flat | Exponential curve |
| 3 | "Increase timeout" for a 301s timeout | Template-based fixes | Context-aware reasoning |
| 4 | Retry rate + timeout = 2 proposals | No deduplication | Merge related findings |
| 5 | Cost analysis misses mixed CLI/API | Only detects API-only | Expand cost strategies |
| 6 | Guard always blocks ($0 budget) | Hardcoded estimates | Use actual UsageRecord data |

## Design Decisions

### Decision 1: Upgrade in-place, don't replace

The `AnalysisFinding` dataclass and `ImprovementProposal` model already have the right fields. We upgrade the logic inside the three services, not the data contracts. The API endpoints and frontend remain unchanged.

**Why:** Adding new models/endpoints would double the surface area for a quality improvement. The existing pipeline (analyze → propose → review → approve → convert) is correct; the content flowing through it needs to be better.

### Decision 2: Scoring in the analyzer, not the generator

The `AnalysisFinding` dataclass gains three score fields (`confidence_score`, `impact_score`, `data_quality_score`). The analyzer computes them. The generator uses them for prioritization and deduplication. The API returns them.

**Why:** Scores are properties of the data analysis, not the proposal formatting. Computing them early lets the generator make better decisions about what to keep, merge, or drop.

### Decision 3: Finding fusion in the generator

The generator receives all findings and applies deduplication before creating proposals. Findings that share the same root cause (e.g., "timeout failures" and "high retry rate for backend") merge into a single, richer proposal.

**Why:** The user sees one actionable improvement instead of two overlapping ones. Merging is a presentation concern, not a detection concern — the analyzer should still report all findings independently.

### Decision 4: Guard uses real data

The guard queries `UsageRecord` for actual costs and `BudgetConfigDB` for limits. A `dev_mode` flag (default: True in development, False in production) controls whether budget blocks are warnings or hard blocks.

**Why:** The current hardcoded $0.05/run estimate blocks all proposals in development. Real data + dev_mode makes the guard useful in both environments.

## Component Changes

### 1. AnalysisFinding Dataclass (additive fields)

**File**: `backend/app/services/research_analyzer.py`

```python
@dataclass
class AnalysisFinding:
    # ... existing fields unchanged ...

    # NEW: Insight scoring
    confidence_score: float = 0.0    # 0.0-1.0: how reliable is this finding?
    impact_score: float = 0.0        # 0.0-1.0: how much improvement possible?
    data_quality_score: float = 0.0   # 0.0-1.0: how much data supports this?

    # NEW: Context for intelligent suggestions
    root_cause_tag: str = ""         # e.g., "timeout_too_tight", "quota_limit_reached"
    context_data: dict = field(default_factory=dict)
    # Holds raw data for suggestion engine:
    # {
    #   "durations": [280.0, 288.0, 296.0, 304.0],
    #   "error_messages": ["Timed out at 280s", ...],
    #   "same_task": true,
    #   "consecutive": true,
    #   "timeout_limit": 300,
    #   "provider": "claude_code",
    #   "execution_mode": "cli",
    # }
```

### 2. ResearchAnalyzer (logic upgrade)

**File**: `backend/app/services/research_analyzer.py`

#### 2.1 Minimum Sample Thresholds

```python
# Constants
_MIN_RUNS_FAILURE = 3      # failure patterns: need ≥3 failed runs
_MIN_RUNS_PERFORMANCE = 5  # performance: need ≥5 total runs per agent
_MIN_RUNS_COST = 8         # cost analysis: need ≥8 runs total
```

Applied at the top of each `analyze_*` method. If the run count is below threshold, return empty list immediately.

#### 2.2 Severity Model Redesign

Replace `_severity_from_count()` with exponential scaling that also considers concentration and consecutiveness:

```python
def _compute_severity(
    self,
    failure_count: int,
    same_task: bool,
    consecutive: bool,
) -> str:
    # Base severity from count (exponential)
    if failure_count >= 7:
        base = "critical"
    elif failure_count >= 4:
        base = "high"
    elif failure_count >= 2:
        base = "medium"
    else:
        base = "low"

    # Boost: same task = concentrated problem (worse than distributed)
    if same_task and base == "medium":
        base = "high"
    elif same_task and base == "high":
        base = "critical"

    # Boost: consecutive failures = active degradation
    if consecutive and base == "medium":
        base = "high"

    return base
```

Detection of `same_task`: all runs have the same `task_id`.
Detection of `consecutive`: the failed runs are the most recent N runs for that task (no successful runs in between).

#### 2.3 Context-Aware Suggestions

Replace `_suggest_fix()` with `_generate_contextual_fix()`:

```python
def _generate_contextual_fix(self, finding: AnalysisFinding) -> str:
    ctx = finding.context_data
    tag = finding.root_cause_tag

    if tag == "timeout_too_tight":
        durations = ctx.get("durations", [])
        limit = ctx.get("timeout_limit", 300)
        if durations:
            max_dur = max(durations)
            suggested = int(max_dur * 1.2)  # 20% headroom
            mode = ctx.get("execution_mode", "unknown")
            return (
                f"{mode.upper()} subprocess timed out at {max_dur:.0f}s "
                f"(limit {limit}s). Increase timeout to {suggested}s "
                f"or decompose into smaller tasks."
            )

    elif tag == "quota_limit_reached":
        provider = ctx.get("provider", "unknown")
        limit = ctx.get("quota_limit", "unknown")
        return (
            f"{provider} quota exhausted at {limit} sessions. "
            f"Options: (1) increase quota, (2) add API fallback for quota peaks, "
            f"(3) implement request queuing to stay within limits."
        )

    elif tag == "model_error":
        model = ctx.get("model", "unknown")
        errors = ctx.get("error_messages", [])
        if errors:
            return (
                f"{model} returned errors: '{errors[0][:80]}'. "
                f"Add retry logic with exponential backoff and fallback to "
                f"a different model tier."
            )

    # ... additional tags ...

    # Fallback: still better than nothing
    return f"Investigate root cause of {finding.finding_type}. Evidence: {finding.description}"
```

Root cause tags are determined by a new `_classify_root_cause()` method:

```python
def _classify_root_cause(self, failure_type: str, runs: list[Run]) -> tuple[str, dict]:
    """Returns (root_cause_tag, context_data) for intelligent suggestions."""
    ctx: dict = {}

    if failure_type == "timeout":
        durations = [r.duration_seconds for r in runs if r.duration_seconds]
        ctx["durations"] = durations
        ctx["timeout_limit"] = 300  # default, could read from config
        ctx["execution_mode"] = runs[0].execution_mode
        ctx["same_task"] = len(set(r.task_id for r in runs)) == 1
        ctx["consecutive"] = self._are_consecutive_failures(runs)
        tag = "timeout_too_tight"

    elif failure_type == "quota_block":
        ctx["provider"] = runs[0].provider
        ctx["execution_mode"] = runs[0].execution_mode
        ctx["quota_limit"] = "hourly limit"
        tag = "quota_limit_reached"

    elif failure_type == "model_error":
        ctx["model"] = runs[0].model
        ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
        tag = "model_error"

    elif failure_type == "cli_error":
        ctx["provider"] = runs[0].provider
        ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
        tag = "cli_binary_issue"

    elif failure_type == "validation_failed":
        ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
        tag = "validation_gap"

    else:
        ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
        tag = "unknown_failure"

    return tag, ctx
```

#### 2.4 Insight Scoring

Each finding gets three scores computed from data:

```python
def _compute_confidence(self, runs: list[Run], same_task: bool) -> float:
    """How reliable is this finding? Based on data volume and consistency."""
    count = len(runs)
    if count >= 10:
        confidence = 0.95
    elif count >= 5:
        confidence = 0.80
    elif count >= 3:
        confidence = 0.60
    else:
        confidence = 0.30

    # Same task = more confident (controlled variable)
    if same_task:
        confidence = min(1.0, confidence + 0.10)

    return round(confidence, 2)

def _compute_impact(self, failure_count: int, total_runs: int) -> float:
    """How much improvement is possible? Based on failure fraction."""
    if total_runs == 0:
        return 0.0
    fraction = failure_count / total_runs
    # Scale: 10% failure = 0.3, 50% = 0.7, 80%+ = 0.95
    return round(min(0.95, fraction * 1.2 + 0.15), 2)

def _compute_data_quality(self, runs: list[Run]) -> float:
    """How complete is the supporting data? Based on field population."""
    if not runs:
        return 0.0
    fields_checked = 0
    fields_populated = 0
    for r in runs[:10]:
        fields_checked += 4  # error_message, duration_seconds, provider, model
        if r.error_message:
            fields_populated += 1
        if r.duration_seconds is not None:
            fields_populated += 1
        if r.provider and r.provider != "unknown":
            fields_populated += 1
        if r.model and r.model != "unknown":
            fields_populated += 1
    return round(fields_populated / fields_checked, 2) if fields_checked else 0.0
```

#### 2.5 Cost Analysis Upgrade

Expand `analyze_costs()` with three new detection strategies:

```python
async def analyze_costs(self, project_id: str, db: AsyncSession) -> list[AnalysisFinding]:
    runs = await self._get_project_runs(project_id, db)
    if len(runs) < _MIN_RUNS_COST:
        return []

    findings: list[AnalysisFinding] = []
    by_mode: dict[str, list[Run]] = {}
    for r in runs:
        by_mode.setdefault(r.execution_mode, []).append(r)

    # Strategy 1: API-only (existing)
    api_runs = by_mode.get("api", [])
    cli_runs = by_mode.get("cli", [])
    if len(api_runs) > 10 and len(cli_runs) == 0:
        # ... existing finding ...

    # Strategy 2: Mixed mode — CLI available but some tasks use expensive API
    if cli_runs and api_runs:
        api_by_agent: dict[str, list[Run]] = {}
        for r in api_runs:
            api_by_agent.setdefault(r.agent_type, []).append(r)
        for agent_type, agent_api in api_by_agent.items():
            if len(agent_api) >= 3:
                findings.append(AnalysisFinding(
                    finding_type="cost_optimization",
                    severity="medium",
                    title=f"{agent_type} agent uses API ({len(agent_api)}x) despite CLI availability",
                    description=f"CLI provider available but {agent_type} ran {len(agent_api)} tasks via paid API",
                    suggested_fix=f"Route {agent_type} tasks to CLI provider for $0 marginal cost. "
                                  f"Current API cost: ${sum(0.05 for _ in agent_api):.2f} estimated.",
                    expected_impact=f"${len(agent_api) * 0.05:.2f}/cycle savings",
                    # ... evidence links ...
                ))

    # Strategy 3: Inefficient routing (high-tier model for simple tasks)
    # Check if high-tier models used for tasks that classify as "simple"
    # This requires cross-referencing with classify_task from model_router
    high_model_runs = [r for r in runs if "opus" in (r.model or "").lower() or "gpt-4" in (r.model or "").lower()]
    if len(high_model_runs) >= 3:
        # Check if these were for simple content (short content = proxy for simple)
        simple_high = [r for r in high_model_runs if r.duration_seconds and r.duration_seconds < 10]
        if len(simple_high) >= 3:
            findings.append(AnalysisFinding(
                finding_type="cost_optimization",
                severity="low",
                title=f"High-tier model used for {len(simple_high)} quick tasks",
                description=f"{len(simple_high)} runs completed in <10s using expensive models",
                suggested_fix="Route quick tasks (<10s) to lower-tier models for cost savings",
                expected_impact=f"~${len(simple_high) * 0.03:.2f}/cycle savings from model downgrading",
                # ...
            ))

    return findings
```

### 3. ProposalGenerator (deduplication + score usage)

**File**: `backend/app/services/proposal_generator.py`

#### 3.1 Finding Fusion

New method `_deduplicate_findings()` that merges related findings before creating proposals:

```python
def _deduplicate_findings(self, findings: list[AnalysisFinding]) -> list[AnalysisFinding]:
    """Merge findings that share the same root cause."""
    groups: dict[str, list[AnalysisFinding]] = {}
    ungrouped: list[AnalysisFinding] = []

    for f in findings:
        # Group by (affected_agent + overlapping run IDs)
        key = self._fusion_key(f)
        if key:
            groups.setdefault(key, []).append(f)
        else:
            ungrouped.append(f)

    merged: list[AnalysisFinding] = []
    for key, group in groups.items():
        if len(group) <= 1:
            merged.extend(group)
            continue
        # Merge: keep highest severity, combine evidence, pick best suggestion
        primary = group[0]
        for other in group[1:]:
            primary = self._merge_two(primary, other)
        merged.append(primary)

    return merged + ungrouped

def _fusion_key(self, f: AnalysisFinding) -> str | None:
    """Determine if this finding shares a root cause with others."""
    # Same agent + overlapping runs = same root cause
    if f.related_agent_type and f.related_run_ids:
        return f"{f.related_agent_type}:{','.join(sorted(f.related_run_ids[:3]))}"
    return None

def _merge_two(self, a: AnalysisFinding, b: AnalysisFinding) -> AnalysisFinding:
    """Merge two findings into one richer finding."""
    # Keep the more specific one (failure_pattern > performance_degradation)
    if a.finding_type == "failure_pattern":
        primary, secondary = a, b
    else:
        primary, secondary = b, a

    # Combine evidence
    primary.evidence = primary.evidence + secondary.evidence
    primary.related_run_ids = list(set(primary.related_run_ids + secondary.related_run_ids))
    primary.related_task_ids = list(set(primary.related_task_ids + secondary.related_task_ids))

    # Use the more specific suggestion
    if len(secondary.suggested_fix) > len(primary.suggested_fix):
        primary.suggested_fix = secondary.suggested_fix

    # Combine descriptions
    primary.description = f"{primary.description} (also: {secondary.description})"

    # Use higher severity
    if self._severity_rank(secondary.severity) > self._severity_rank(primary.severity):
        primary.severity = secondary.severity

    # Average scores
    primary.confidence_score = round((a.confidence_score + b.confidence_score) / 2, 2)
    primary.impact_score = round(max(a.impact_score, b.impact_score), 2)
    primary.data_quality_score = round((a.data_quality_score + b.data_quality_score) / 2, 2)

    return primary
```

#### 3.2 Score-Informed Prioritization

Replace the simple `severity × count` scoring with score-aware prioritization:

```python
def _prioritize_findings(self, findings: list[AnalysisFinding]) -> list[AnalysisFinding]:
    def score(f: AnalysisFinding) -> float:
        severity_w = _SEVERITY_WEIGHT.get(f.severity, 1)
        confidence_w = f.confidence_score or 0.5
        impact_w = f.impact_score or 0.5
        count = len(f.related_run_ids) or 1
        return severity_w * confidence_w * impact_w * count
    return sorted(findings, key=score, reverse=True)
```

### 4. RDManager Guard (realism fix)

**File**: `backend/app/services/rd_manager.py` — `run_approval_guard()` method only

#### 4.1 Real Cost Estimation

Replace hardcoded $0.05/run with actual UsageRecord data:

```python
async def _estimate_implementation_cost(self, db: AsyncSession) -> tuple[float, bool]:
    """Estimate cost from actual usage data. Returns (cost, requires_paid)."""
    try:
        from app.models import UsageRecord
        result = await db.execute(
            select(UsageRecord).order_by(UsageRecord.created_at.desc()).limit(10)
        )
        records = result.scalars().all()

        if records:
            avg_cost = sum(r.cost_usd for r in records) / len(records)
            return avg_cost * 4, any(r.cost_usd > 0 for r in records)

        # No usage records exist yet — estimate from provider config
        from app.providers.registry import ProviderRegistry
        from app.config.model_config import load_config
        config = load_config()
        registry = ProviderRegistry(config)
        has_cli = registry.has_cli_providers()
        if has_cli:
            return 0.0, False
        return 4 * 0.05, True
    except Exception:
        return 4 * 0.05, True
```

#### 4.2 Dev Mode

```python
import os

_DEV_MODE = os.getenv("ORKA_DEV_MODE", "true").lower() == "true"
```

When `_DEV_MODE` is True:
- Budget blocks become **warnings**, not blocks (can still proceed)
- `can_proceed` stays True unless there are non-budget blocks
- A warning is added: "Development mode — budget limits advisory"

When `_DEV_MODE` is False (production):
- Budget blocks are hard blocks
- `can_proceed = False` when budget doesn't fit

## What Stays the Same

- All API endpoints (no new ones)
- All API schemas (no new response fields at the API level)
- All frontend components (ProposalCard already displays all fields)
- ImprovementProposal model (no schema changes)
- Status transition logic (untouched)
- Goal/Run/Task models (untouched)
- Phase 1-3C behavior completely preserved

## What Gets Removed / Deprecated

Nothing removed. All changes are logic upgrades inside existing services.

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/research_analyzer.py` | Sample thresholds, exponential severity, context-aware fixes, root cause classification, insight scoring, expanded cost analysis |
| `backend/app/services/proposal_generator.py` | Finding deduplication/fusion, score-aware prioritization |
| `backend/app/services/rd_manager.py` | Real cost estimation from UsageRecord, dev_mode for guard |

## Acceptance Criteria

- [ ] No findings generated when sample size below threshold (< 3 failures, < 5 performance runs)
- [ ] 4 failures → severity "high" (was "low")
- [ ] 7+ failures → severity "critical"
- [ ] Same-task failures boost severity one level
- [ ] Consecutive failures boost severity one level
- [ ] Suggestions include specific numbers (duration, timeout limit, provider name)
- [ ] "CLI timed out at 301s (limit 300s). Increase to 361s or decompose." — not "Increase timeout"
- [ ] Timeout + retry rate for same agent → single merged proposal
- [ ] Mixed CLI/API usage detected and reported with cost estimate
- [ ] Guard uses actual UsageRecord costs, not hardcoded $0.05
- [ ] Guard dev_mode: budget blocks become warnings, can_proceed stays True
- [ ] Each proposal has confidence_score, impact_score, data_quality_score
- [ ] No new API endpoints, models, or frontend changes
- [ ] All Phase 1-4 regression tests still pass
