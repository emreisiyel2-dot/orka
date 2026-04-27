# Phase 5: R&D Intelligence Upgrade — Design Spec

Date: 2026-04-25
Status: Ready for Implementation
Scope: Phase 5
Depends on: Phase 4 (R&D / Improvement Lab)

## Summary

Upgrade the R&D analysis engine from template-based pattern detection to context-aware intelligent reasoning. The current system works structurally but produces generic, noisy output. This phase makes proposals feel like a senior engineer's review — specific, actionable, and prioritized by real impact.

**No new models. No new API endpoints. No new frontend components.** Only upgrade three services: `ResearchAnalyzer`, `ProposalGenerator`, and `RDManager.run_approval_guard()`.

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

### Decision 4: Fusion key uses agent_type + root_cause_tag, not run IDs

The deduplication key is `{affected_agent_type}:{root_cause_tag}` rather than overlapping run ID sets. Two findings for the same agent with the same root cause (e.g., "timeout" failures + "high retry rate" both from timeouts) get merged.

**Why:** Overlapping run IDs is fragile — the same agent can have different run IDs for genuinely different issues. Root cause tag is semantically meaningful: if two findings point to the same root cause for the same agent, they're the same problem.

### Decision 5: Guard uses real data with dev_mode toggle

The guard queries `UsageRecord` for actual costs and `BudgetConfigDB` for limits. A `dev_mode` flag (env `ORKA_DEV_MODE`, default "true" in development) controls whether budget blocks are warnings or hard blocks.

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
```

### 2. ResearchAnalyzer (logic upgrade)

**File**: `backend/app/services/research_analyzer.py`

#### 2.1 Minimum Sample Thresholds

```python
# Constants at module level
_MIN_RUNS_FAILURE = 3      # failure patterns: need >=3 failed runs
_MIN_RUNS_PERFORMANCE = 5  # performance: need >=5 total runs per agent
_MIN_RUNS_COST = 8         # cost analysis: need >=8 runs total
```

Applied at the top of each `analyze_*` method. If the run count is below threshold, return empty list immediately.

**Reasoning for thresholds:**
- 3 failures: Below 3, a pattern could be coincidence. At 3+, it's statistically worth reporting.
- 5 performance: Performance variance needs more data points to distinguish signal from noise.
- 8 cost: Cost patterns need meaningful volume to justify routing changes.

#### 2.2 Severity Model Redesign

Replace `_severity_from_count()` with exponential scaling + contextual boosts:

```python
def _compute_severity(self, failure_count: int, same_task: bool, consecutive: bool) -> str:
    # Base severity from count (exponential curve)
    if failure_count >= 7:
        base = "critical"
    elif failure_count >= 4:
        base = "high"
    elif failure_count >= 2:
        base = "medium"
    else:
        base = "low"

    # Boost: same task = concentrated problem
    if same_task and base in ("medium", "high"):
        base = {"medium": "high", "high": "critical"}[base]

    # Boost: consecutive failures = active degradation
    if consecutive and base == "medium":
        base = "high"

    return base
```

**Reasoning:**
- Same-task failures mean a specific task is broken, not random flakiness. Higher urgency.
- Consecutive failures (no successes in between) mean the problem is active and worsening.
- Both boosts can combine: 4 same-task consecutive failures = critical.

#### 2.3 Consecutive Failure Detection

```python
def _are_consecutive_failures(self, failed_runs: list[Run], all_runs: list[Run]) -> bool:
    """Check if the most recent runs for this failure type are all failures."""
    if len(failed_runs) < 2:
        return False
    # Sort failed runs by creation time descending
    sorted_fails = sorted(failed_runs, key=lambda r: r.created_at, reverse=True)
    # Check if the most recent failed run is also the most recent overall run
    latest_overall = max(all_runs, key=lambda r: r.created_at)
    return sorted_fails[0].id == latest_overall.id
```

**Reasoning:** True consecutive means failures are the most recent activity. If there are successes after the failures, the problem may have resolved itself.

#### 2.4 Context-Aware Suggestions

Replace `_suggest_fix()` with `_generate_contextual_fix()` that reads from `context_data`:

- `timeout_too_tight`: Shows actual duration vs limit, suggests specific timeout value (120% of max observed).
- `quota_limit_reached`: Shows provider, suggests 3 options (increase quota, API fallback, request queuing).
- `model_error`: Shows actual error message and model name, suggests retry with backoff.
- `cli_binary_issue`: Shows provider and error, suggests health checks.
- `validation_gap`: Shows error messages, suggests pre-execution validation.

#### 2.5 Root Cause Classification

New `_classify_root_cause()` method that produces `(root_cause_tag, context_data)` for each failure type:

- Populates `context_data` with durations, error messages, execution mode, provider, model
- Detects `same_task` and `consecutive` for severity boosting
- Provides structured data for the suggestion engine

#### 2.6 Insight Scoring

Three scores per finding:

- **confidence_score**: Based on run count (3→0.60, 5→0.80, 10→0.95) + 0.10 boost for same-task
- **impact_score**: Based on failure fraction of total runs (10%→0.3, 50%→0.7, 80%→0.95)
- **data_quality_score**: Based on field population rate across runs (error_message, duration, provider, model)

#### 2.7 Cost Analysis Upgrade

Three strategies:

1. **API-only** (existing): No CLI providers configured, all runs use paid API.
2. **Mixed mode**: CLI available but some agents use API. Reports specific agent + count.
3. **Inefficient routing**: High-tier models used for short-duration tasks (proxy for "simple").

Minimum threshold: 8 runs total before any cost analysis.

### 3. ProposalGenerator (deduplication + score usage)

**File**: `backend/app/services/proposal_generator.py`

#### 3.1 Finding Fusion

New `_deduplicate_findings()` that groups by `{agent_type}:{root_cause_tag}`:

- Same agent + same root cause → merge into one finding
- Merge strategy: keep failure_pattern over performance_degradation, combine evidence, use more specific suggestion, take higher severity, average scores

#### 3.2 Score-Informed Prioritization

Replace simple `severity * count` with `severity_weight * confidence * impact * count`.

**Reasoning:** A high-severity finding with low confidence (3 runs) should rank below a medium-severity finding with high confidence (15 runs).

### 4. RDManager Guard (realism fix)

**File**: `backend/app/services/rd_manager.py` — `run_approval_guard()` method only

#### 4.1 Real Cost Estimation

Query `UsageRecord` for actual average cost per run, fall back to provider config check, final fallback to $0.05.

#### 4.2 Dev Mode

```python
import os
_DEV_MODE = os.getenv("ORKA_DEV_MODE", "true").lower() == "true"
```

- **dev_mode=True**: Budget blocks become warnings, `can_proceed` stays True
- **dev_mode=False**: Budget blocks are hard blocks, `can_proceed = False`

## What Stays the Same

- All API endpoints (no new ones)
- All API schemas (no new response fields at the API level)
- All frontend components (ProposalCard already displays all fields)
- ImprovementProposal model (no schema changes)
- Status transition logic (untouched)
- Goal/Run/Task models (untouched)
- Phase 1-4 behavior completely preserved

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/research_analyzer.py` | Sample thresholds, exponential severity, context-aware fixes, root cause classification, insight scoring, expanded cost analysis |
| `backend/app/services/proposal_generator.py` | Finding deduplication/fusion, score-aware prioritization |
| `backend/app/services/rd_manager.py` | Real cost estimation from UsageRecord, dev_mode for guard |

## Acceptance Criteria

- [ ] No findings generated when sample size below threshold (<3 failures, <5 performance runs)
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
