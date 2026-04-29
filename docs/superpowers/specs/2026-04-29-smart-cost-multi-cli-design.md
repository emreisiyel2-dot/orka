# Phase 5.6: Smart Cost Optimization + Multi-CLI Provider Routing — Design Spec (v3)

Date: 2026-04-25
Status: Draft
Scope: Phase 5.6
Depends on: Phase 5.5 (Reality Hardening)
Revision: v3 — route() is pure forwarder, explicit adaptive thresholds, adaptive context limits, defined trim priority

## Summary

Reduce token/quota usage and optimize model/provider selection by extending existing systems. ModelRouter becomes a **pure decision engine** — `decide()` evaluates providers and returns routing metadata without executing. `route()` is a **pure forwarding wrapper** that calls `decide()` then delegates execution to the existing `_execute_cli()` / `_try_api_route()` helpers with zero additional routing logic. The execution layer (worker/orchestrator) is responsible for retry/fallback. Add complexity-aware CLI routing with explicit adaptive thresholds, structured context optimization with adaptive token limits, richer usage tracking, and explainable routing decisions. All changes are additive. No new tables.

## Problem Statement

| # | Problem | Root Cause | Fix |
|---|---------|-----------|-----|
| 1 | All tasks routed equally regardless of complexity | classify_task() exists but routing ignores complexity | Complexity-aware tier mapping in decision engine |
| 2 | Only one CLI provider tried per task | _try_cli_route picks first healthy, no fallback chain | Decision engine returns ordered provider list; execution layer iterates |
| 3 | Full context sent for every task | No context trimming before execution | ContextOptimizer with adaptive token limits and structured tiers |
| 4 | Failed low-tier tasks not retried at higher tier | No retry escalation logic | Retry escalation in execution layer, not router |
| 5 | CLI session stats lack per-provider detail and adaptive signals | CLIQuotaTracker tracks counts but not errors, health, or success rates | Enrich CLIQuotaTracker with error tracking and adaptive signals |
| 6 | Routing decisions lack explainability | RoutingDecision has no task_complexity, considered/rejected providers | Add fields for full routing transparency |
| 7 | Stats don't show provider-level detail | /api/system/stats is system-wide only | Add provider breakdown |

## Architecture Overview

```
Task → classify_task() → TaskProfile(complexity, task_type)
                ↓
        ContextOptimizer.trim() → trimmed_prompt
                ↓
        ModelRouter.decide() → RoutingDecision (PURE DECISION, no execution)
           ├─ lookup_cli_policy(complexity, task_type) → base provider order
           ├─ _reorder_by_adaptive_signals() → final provider order
           ├─ evaluate each provider: quota + health check
           ├─ select model by complexity tier
           ├─ populate considered_providers, rejected_providers
           └─ return RoutingDecision with routing metadata
                ↓
        ModelRouter.route() → PURE FORWARDER (zero routing logic)
           ├─ calls decide()
           └─ delegates execution to _execute_cli() or _try_api_route()
                ↓
        Execution Layer (worker/orchestrator) — future enhancement
           ├─ Execute with decision.selected_provider
           │      ↓ fail
           ├─ Try decision.considered_providers (CLI→CLI fallback chain)
           │      ↓ all CLI fail
           ├─ Retry with escalated model tier (max 2 retries)
           │      ↓ all fail
           └─ Mark action_required → task paused, no API fallback
```

**Key architectural constraints:**
- `decide()` is the single source of routing truth. It never executes.
- `route()` contains **zero routing logic** — it calls `decide()` and delegates execution. No conditionals, no fallback chains, no retry logic inside `route()`.
- The execution layer (future) handles retry/fallback by reading RoutingDecision metadata.

## Design Decisions

### Decision 1: ModelRouter as pure decision engine

ModelRouter's `decide()` method evaluates all available providers, applies the routing policy with adaptive reordering, and returns a `RoutingDecision` with:
- `selected_provider` and `selected_model` — the recommended choice
- `considered_providers` — JSON list of all providers evaluated
- `rejected_providers` — JSON list of providers rejected with reasons
- `task_complexity` — classification result
- `selected_cli_provider` — which CLI provider was selected

The router does NOT call `provider.complete()`, does NOT retry, and does NOT fall back.

### Decision 2: route() is a pure forwarding wrapper

`route()` exists solely for backward compatibility with Phase 1-5.5 callers. Its contract:

```python
async def route(self, prompt, profile, task_id, db):
    decision = await self.decide(prompt, profile, task_id, db)
    # NO if/else routing logic. NO fallback chains. NO retry logic.
    # Just forward to the appropriate execution helper.
    return await self._execute_decision(decision, prompt, profile, task_id, db)
```

`route()` must not contain any routing decisions, provider iteration, fallback chains, or conditional logic beyond "which execution helper to call." All routing intelligence lives in `decide()`.

**Why:** Single source of truth. If routing policy changes, only `decide()` changes. `route()` is just glue.

### Decision 3: Routing policy with explicit adaptive thresholds

A `CLI_ROUTING_POLICY` dict maps `(task_type, complexity)` tuples to an ordered list of preferred CLI providers (static base). The router reorders using adaptive signals from CLIQuotaTracker with **explicit, documented thresholds**:

| Signal | Threshold | Action |
|--------|-----------|--------|
| `recent_failure_rate > 0.5` with `>= 3 total sessions` | High failure | **Deprioritize** — add +30 to score |
| `recent_failure_rate > 0.2` with `>= 3 total sessions` | Elevated failure | **Deprioritize** — add +15 to score |
| `recent_success_rate > 0.8` with `>= 5 total sessions` | High success | **Boost** — subtract 10 from score |
| `status == "blocked"` | Hard block | **Skip entirely** — add +50 to score |
| `status == "throttled"` | Soft limit | **Deprioritize** — add +20 to score |
| No data (provider never used) | Unknown | **Use static order** — base score only (no penalty, no boost) |

**No-data rule:** When a provider has zero session history, it receives only its base policy-position score. No artificial penalty, no artificial boost. This ensures new providers get a fair chance.

**Why:** Explicit thresholds prevent hidden heuristics. The boost rule (>0.8 success with ≥5 runs) rewards consistently reliable providers. The no-data rule ensures fairness for new providers.

### Decision 4: CLI→CLI fallback in execution layer, never silent CLI→API

If the selected CLI provider fails during execution, the execution layer checks `RoutingDecision.considered_providers` for the next available provider and tries it. If all CLI providers fail, the execution layer marks the task as `action_required` and pauses. No silent API fallback.

**Why:** The user explicitly stated: "NEVER fallback silently to paid API." This is a hard constraint.

### Decision 5: Context optimization with adaptive token limits and structured tiers

`ContextOptimizer` classifies prompt content into three tiers with **explicit priority order**:

```
Trimming priority (preserved first → dropped last):
  REQUIRED  — always preserved (task instruction, current file contents, error messages)
  RELEVANT  — trimmed to history window (recent conversation, related file snippets, prior decisions)
  OPTIONAL  — dropped first (full git diffs, verbose logs, historical context beyond window)
```

**Adaptive `max_context_tokens` by budget tier:**

| Budget Tier | max_context_tokens | Rationale |
|-------------|-------------------|-----------|
| `low` | 2,000 – 4,000 | Simple tasks, minimal context needed |
| `medium` | 4,000 – 8,000 | Standard tasks, moderate context |
| `high` | up to 16,000 | Complex tasks, maximum context within safe limits |

The optimizer receives `budget_tier` alongside `complexity` and `task_type`. It selects `max_context_tokens` from the tier range and applies trimming when context exceeds that limit.

**History window rules** (applied when RELEVANT tier needs trimming):

| task_type + complexity | keep_recent (message blocks) |
|----------------------|------------------------------|
| analysis/review + complex | 10 |
| code_gen + complex | 8 |
| planning + complex | 8 |
| default (medium) | 5 |
| docs/planning + simple | 3 |

**Trimming process:**
1. Count tokens (approximate: words × 2). If within limit → return as-is.
2. If over limit → drop OPTIONAL content (blocks beyond history window).
3. If still over → trim RELEVANT content to history window for the task_type+complexity.
4. REQUIRED content is never trimmed.

**Why:** Token budgets should match task investment. A $0.01 simple task shouldn't send 16k tokens. Adaptive limits compound savings across all tasks.

### Decision 6: Retry escalation in execution layer

When a provider execution fails, the execution layer can:
1. Try the next provider from `considered_providers` (CLI→CLI fallback)
2. Escalate model tier within the same provider (low→medium→high), max 2 retries
3. If all options exhausted, mark `action_required`

**Why:** Separate from the decision engine. The execution layer knows runtime context and can make better retry decisions.

### Decision 7: Enrich existing models, no new tables

- `RoutingDecision`: add `task_complexity`, `selected_cli_provider`, `fallback_reason`, `considered_providers`, `rejected_providers` columns
- `CLIQuotaTracker.CLISessionUsage`: add `last_error`, `last_success_at`, `last_failure_at`, `last_health_check`, computed `is_available`
- `UsageRecord`: no changes needed
- `/api/system/stats`: add `providers` breakdown dict

**Why:** Zero new tables. Additive columns only.

## Component Changes

### 1. Enhanced Task Complexity Classification

**File:** `backend/app/services/model_router.py` — `classify_task()` function

Current classification uses keyword matching. Enhance with:

```python
_COMPLEXITY_LENGTH_THRESHOLDS = {
    "simple": 500,     # <500 words → likely simple
    "medium": 2000,    # 500-2000 → medium
    "high": float("inf"),  # >2000 → likely complex
}

_CODE_INDICATORS = {"def ", "class ", "import ", "function ", "async ", "```", "return ", "const "}
```

Enhanced logic:
1. Run existing keyword classification (unchanged)
2. If keyword result is "simple" but prompt > 2000 words → upgrade to "medium"
3. If prompt contains ≥3 code indicators → bias toward code_gen task_type
4. If task_type is code_gen/review and complexity is "simple" → keep "simple" (code can be short)

### 2. CLI Routing Policy with Adaptive Signals

**File:** `backend/app/services/model_router.py` — new constants + lookup method

```python
_CLI_ROUTING_POLICY: dict[tuple[str, str], list[str]] = {
    # Complex architecture/debug/refactor → Claude Code first
    ("code_gen", "complex"): ["claude_code", "glm_coding"],
    ("review", "complex"):   ["claude_code", "glm_coding"],
    ("planning", "complex"): ["claude_code", "glm_coding"],

    # Fast/simple coding → GLM first (cheaper, faster)
    ("code_gen", "simple"):  ["glm_coding", "claude_code"],
    ("code_gen", "medium"):  ["glm_coding", "claude_code"],
    ("review", "simple"):    ["glm_coding", "claude_code"],
    ("review", "medium"):    ["claude_code", "glm_coding"],

    # Testing/repo inspection → best available
    ("analysis", "simple"):  ["glm_coding", "claude_code"],
    ("analysis", "medium"):  ["claude_code", "glm_coding"],
    ("analysis", "complex"): ["claude_code"],

    # Docs → least loaded
    ("docs", "simple"):      ["glm_coding", "claude_code"],
    ("docs", "medium"):      ["glm_coding", "claude_code"],
    ("docs", "complex"):     ["claude_code", "glm_coding"],

    # Planning → Claude for complex
    ("planning", "simple"):  ["glm_coding", "claude_code"],
    ("planning", "medium"):  ["claude_code", "glm_coding"],
}

_CLI_DEFAULT_ORDER = ["claude_code", "glm_coding"]


def lookup_cli_policy(task_type: str, complexity: str) -> list[str]:
    """Return ordered list of preferred CLI providers for this task."""
    return _CLI_ROUTING_POLICY.get(
        (task_type, complexity),
        _CLI_DEFAULT_ORDER,
    )
```

**Adaptive reordering with explicit thresholds:**

```python
def _reorder_by_adaptive_signals(
    self, provider_order: list[str], task_type: str, complexity: str,
) -> list[str]:
    """Reorder providers using explicit adaptive thresholds.

    Thresholds:
      - failure_rate > 0.5 with >=3 runs  → +30 (deprioritize)
      - failure_rate > 0.2 with >=3 runs  → +15 (deprioritize)
      - success_rate > 0.8 with >=5 runs  → -10 (boost)
      - status == "blocked"               → +50 (skip)
      - status == "throttled"             → +20 (deprioritize)
      - no data                           → base score only (use static order)
    """
    scored = []
    for i, name in enumerate(provider_order):
        usage = self._cli_quota.get_usage(name)
        signals = self._cli_quota.get_adaptive_signals(name)

        base_score = i * 10

        # Failure penalties (only when enough data)
        total = signals.get("total_sessions", 0)
        failure_rate = signals.get("recent_failure_rate", 0.0)
        success_rate = signals.get("recent_success_rate", 1.0)

        failure_penalty = 0
        if total >= 3:
            if failure_rate > 0.5:
                failure_penalty = 30
            elif failure_rate > 0.2:
                failure_penalty = 15

        # Success boost (only when enough data)
        success_boost = 0
        if total >= 5 and success_rate > 0.8:
            success_boost = 10

        # Status penalties
        status_penalty = 0
        if usage and usage.status == "blocked":
            status_penalty = 50
        elif usage and usage.status == "throttled":
            status_penalty = 20

        # No data → base score only (no penalty, no boost)
        scored.append((name, base_score + failure_penalty - success_boost + status_penalty))

    scored.sort(key=lambda x: x[1])
    return [name for name, _ in scored]
```

### 3. ModelRouter.decide() — Pure Decision Method

**File:** `backend/app/services/model_router.py`

The `decide()` method evaluates providers and returns a RoutingDecision without executing anything:

```python
async def decide(
    self, prompt: str, profile: TaskProfile, task_id: str | None, db: AsyncSession,
) -> RoutingDecision:
    """Pure decision engine — evaluate providers and return routing decision.

    Does NOT execute any provider. Returns a RoutingDecision with
    selected_provider, selected_model, considered_providers, and
    rejected_providers. The execution layer acts on this decision.
    """
    execution_mode = self._resolve_execution_mode(profile)
    if execution_mode == "cli":
        return await self._decide_cli(prompt, profile, task_id, db)
    return await self._decide_api(prompt, profile, task_id, db, execution_mode)


async def _decide_cli(
    self, prompt: str, profile: TaskProfile, task_id: str | None, db: AsyncSession,
) -> RoutingDecision:
    """Decide which CLI provider to use. No execution."""
    cli_providers = self._registry.all_by_mode()["cli"]

    considered = []
    rejected = []
    selected_provider = None
    selected_model = "none"

    base_order = lookup_cli_policy(profile.task_type, profile.complexity)
    provider_order = self._reorder_by_adaptive_signals(
        base_order, profile.task_type, profile.complexity,
    )
    provider_map = {p.name: p for p in cli_providers}

    for provider_name in provider_order:
        provider = provider_map.get(provider_name)
        if provider is None:
            continue

        considered.append(provider_name)
        quota_status = self._cli_quota.check_available(provider_name)

        if quota_status == "blocked":
            rejected.append({"provider": provider_name, "reason": "quota_blocked"})
            continue

        healthy = await provider.health_check()
        if not healthy:
            rejected.append({"provider": provider_name, "reason": "health_check_failed"})
            continue

        models = provider.get_models()
        selected_model = self._select_model_by_complexity(models, profile.complexity)
        selected_provider = provider_name
        break

    reason = "cli_primary" if selected_provider else "all_cli_unavailable"
    decision = RoutingDecision(
        task_id=task_id,
        agent_type=profile.agent_type,
        requested_tier=profile.budget_tier,
        selected_model=selected_model,
        selected_provider=selected_provider or "none",
        reason=reason,
        quota_status="available" if selected_provider else "exhausted",
        cost_estimate=0.0,
        execution_mode="cli",
        task_complexity=profile.complexity,
        selected_cli_provider=selected_provider,
        considered_providers=json.dumps(considered) if considered else None,
        rejected_providers=json.dumps(rejected) if rejected else None,
    )
    if selected_provider is None:
        decision.blocked_reason = "all_cli_providers_unavailable"

    db.add(decision)
    await db.flush()
    return decision
```

Helper for complexity-aware model selection:

```python
def _select_model_by_complexity(self, models: list[ModelInfo], complexity: str) -> str:
    """Select appropriate model tier based on task complexity."""
    if not models:
        return "unknown"

    tier_order = {"low": 0, "medium": 1, "high": 2}
    sorted_models = sorted(models, key=lambda m: tier_order.get(m.tier, 1))

    if complexity == "simple":
        return sorted_models[0].id
    elif complexity == "complex":
        return sorted_models[-1].id
    else:
        medium = [m for m in sorted_models if m.tier == "medium"]
        if medium:
            return medium[0].id
        return sorted_models[len(sorted_models) // 2].id
```

### 4. route() — Pure Forwarding Wrapper

**File:** `backend/app/services/model_router.py`

`route()` contains **zero routing logic**. It calls `decide()` and delegates execution:

```python
async def route(
    self, prompt: str, profile: TaskProfile, task_id: str | None, db: AsyncSession,
) -> tuple[ProviderResponse | None, RoutingDecision | None]:
    """Pure forwarding wrapper — calls decide() and delegates execution.

    Contains NO routing logic, NO fallback chains, NO retry logic.
    All routing intelligence lives in decide().
    """
    decision = await self.decide(prompt, profile, task_id, db)

    if decision.blocked_reason:
        return None, decision

    if decision.execution_mode == "cli":
        response = await self._execute_cli(decision, prompt, profile, task_id, db)
    else:
        response = await self._try_api_route(prompt, profile, task_id, db, decision.execution_mode)

    if response is not None:
        return response, decision
    return None, decision
```

### 5. Context Optimization with Adaptive Token Limits

**File:** `backend/app/services/context_optimizer.py` — NEW FILE

```python
"""Context optimizer — trims prompts before execution to reduce token usage.

Content tiers (trimming priority — preserved first, dropped last):
  REQUIRED  — task instruction, current file contents, error messages
  RELEVANT  — recent conversation history, related file snippets, prior decisions
  OPTIONAL  — full git diffs, verbose logs, historical context beyond window

Trimming process:
  1. If within max_context_tokens → return as-is
  2. If over → drop OPTIONAL content (blocks beyond history window)
  3. If still over → trim RELEVANT to history window
  4. REQUIRED is never trimmed
"""

_TOKENS_PER_WORD = 2

# Adaptive token limits by budget tier
_TIER_TOKEN_LIMITS: dict[str, tuple[int, int]] = {
    "low":    (2000, 4000),
    "medium": (4000, 8000),
    "high":   (8000, 16000),
}

# History window rules: (task_type, complexity) → keep_recent message blocks
_HISTORY_WINDOW: dict[tuple[str, str], int] = {
    ("analysis", "complex"): 10,
    ("review", "complex"): 10,
    ("code_gen", "complex"): 8,
    ("planning", "complex"): 8,
    ("docs", "simple"): 3,
    ("planning", "simple"): 3,
}

_DEFAULT_HISTORY_WINDOW = 5
_DEFAULT_MAX_TOKENS = 8000


class ContextOptimizer:
    def __init__(self, max_context_tokens: int | None = None):
        self._fixed_max_tokens = max_context_tokens

    def trim(self, prompt: str, complexity: str, task_type: str, budget_tier: str = "medium") -> str:
        max_tokens = self._resolve_max_tokens(budget_tier)
        max_words = max_tokens // _TOKENS_PER_WORD

        word_count = len(prompt.split())
        if word_count <= max_words:
            return prompt

        window = _HISTORY_WINDOW.get(
            (task_type, complexity), _DEFAULT_HISTORY_WINDOW
        )
        return self._trim_conversation(prompt, keep_recent=window)

    def _resolve_max_tokens(self, budget_tier: str) -> int:
        if self._fixed_max_tokens is not None:
            return self._fixed_max_tokens
        low, high = _TIER_TOKEN_LIMITS.get(budget_tier, (4000, 8000))
        return high  # Use upper bound of tier range

    def _trim_conversation(self, prompt: str, keep_recent: int) -> str:
        blocks = prompt.split("\n\n")
        if len(blocks) <= keep_recent:
            return prompt

        kept = blocks[-keep_recent:]
        trimmed_count = len(blocks) - keep_recent
        header = f"[{trimmed_count} earlier messages trimmed for context optimization]\n\n"
        return header + "\n\n".join(kept)
```

### 6. Enriched CLIQuotaTracker with Adaptive Signals

**File:** `backend/app/services/cli_quota_tracker.py` — extend `CLISessionUsage`

```python
@dataclass
class CLISessionUsage:
    provider: str
    session_count: int = 0
    total_duration_seconds: float = 0.0
    total_commands: int = 0
    total_prompts: int = 0
    total_tasks: int = 0
    status: str = "available"
    blocked_until: datetime | None = None
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Error/success tracking
    last_error: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_health_check: datetime | None = None
    # Adaptive signals (computed over current window)
    recent_success_count: int = 0
    recent_failure_count: int = 0
```

Computed `is_available`:
```python
def is_available(self, provider: str) -> bool:
    usage = self._usage.get(provider)
    if usage is None:
        return True
    if usage.status == "blocked":
        if usage.blocked_until and datetime.now(timezone.utc) >= usage.blocked_until:
            self.reset(provider)
            return True
        return False
    total = usage.recent_success_count + usage.recent_failure_count
    if total >= 3 and (usage.recent_failure_count / total) > 0.5:
        return False
    return True
```

Adaptive signals (includes `total_sessions` for threshold checks):
```python
def get_adaptive_signals(self, provider: str) -> dict:
    usage = self._usage.get(provider)
    if usage is None:
        return {
            "recent_success_rate": 1.0,
            "recent_failure_rate": 0.0,
            "avg_execution_time": 0.0,
            "is_available": True,
            "total_sessions": 0,
        }
    total_sessions = usage.recent_success_count + usage.recent_failure_count
    success_rate = usage.recent_success_count / total_sessions if total_sessions > 0 else 1.0
    failure_rate = usage.recent_failure_count / total_sessions if total_sessions > 0 else 0.0
    avg_time = usage.total_duration_seconds / usage.session_count if usage.session_count > 0 else 0.0
    return {
        "recent_success_rate": round(success_rate, 3),
        "recent_failure_rate": round(failure_rate, 3),
        "avg_execution_time": round(avg_time, 2),
        "is_available": self.is_available(provider),
        "total_sessions": total_sessions,
    }
```

Provider status (for system stats):
```python
def get_provider_status(self, provider: str) -> dict | None:
    usage = self._usage.get(provider)
    if usage is None:
        return None
    signals = self.get_adaptive_signals(provider)
    return {
        "provider": provider,
        "status": usage.status,
        "active_sessions": self._active_sessions.get(provider, 0),
        "session_count": usage.session_count,
        "total_commands": usage.total_commands,
        "total_prompts": usage.total_prompts,
        "blocked_until": usage.blocked_until.isoformat() if usage.blocked_until else None,
        "last_error": usage.last_error,
        "last_success_at": usage.last_success_at.isoformat() if usage.last_success_at else None,
        "last_failure_at": usage.last_failure_at.isoformat() if usage.last_failure_at else None,
        "last_health_check": usage.last_health_check.isoformat() if usage.last_health_check else None,
        **signals,
    }
```

Updates to existing methods:
- `record_session()`: increment `recent_success_count`, set `last_success_at`
- `mark_blocked()`: increment `recent_failure_count`, set `last_error` and `last_failure_at`
- `check_available()`: set `last_health_check`

### 7. RoutingDecision Model Extensions

**File:** `backend/app/models.py` — add columns to RoutingDecision

```python
# Add after existing RoutingDecision fields (before created_at):
task_complexity: Mapped[str | None] = mapped_column(String(20), nullable=True)
selected_cli_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
fallback_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
considered_providers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
rejected_providers: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON list of {provider, reason}
```

All nullable. All additive. No new tables.

### 8. Enhanced System Stats

**File:** `backend/app/api/system.py` — extend `/api/system/stats`

```python
"providers": {
    "cli": {
        provider_name: {
            "status": ...,
            "session_count": ...,
            "recent_success_rate": ...,
            "recent_failure_rate": ...,
            "avg_execution_time": ...,
            "is_available": ...,
            "total_sessions": ...,
        }
        for provider_name in ("claude_code", "glm_coding")
        if tracker.get_provider_status(provider_name)
    },
}
```

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/model_router.py` | Enhanced classify_task, CLI routing policy, decide() pure decision, _reorder_by_adaptive_signals with explicit thresholds, route() pure forwarder |
| `backend/app/services/context_optimizer.py` | NEW: adaptive token limits by budget tier, structured tiers (REQUIRED > RELEVANT > OPTIONAL), history window rules |
| `backend/app/services/cli_quota_tracker.py` | Enriched CLISessionUsage, computed is_available, get_adaptive_signals (with total_sessions), get_provider_status |
| `backend/app/models.py` | RoutingDecision: add 5 nullable columns |
| `backend/app/api/system.py` | Add provider breakdown to /api/system/stats |
| `backend/app/services/rd_manager.py` | No changes needed |

## What Stays the Same

- All API endpoints (paths and response shapes)
- ImprovementProposal, Run, Task, Goal models
- Phase 1-5.5 behavior preserved (route() signature unchanged)
- CLI providers remain first-class
- quota_only remains default
- ALLOW_PAID_OVERAGE = false remains default
- No silent paid API fallback ever
- ModelRouter.route() still returns (response, decision) tuple
- Execution layer retry/fallback is a future enhancement

## Acceptance Criteria

- [ ] ModelRouter.decide() returns RoutingDecision without executing any provider
- [ ] route() contains zero routing logic — only calls decide() then delegates execution
- [ ] RoutingDecision includes considered_providers (JSON list) and rejected_providers (JSON list with reasons)
- [ ] RoutingDecision includes task_complexity and selected_cli_provider
- [ ] Adaptive thresholds: failure_rate > 0.5 with ≥3 runs deprioritizes, success_rate > 0.8 with ≥5 runs boosts, no data uses static order
- [ ] Simple tasks route to cheapest available CLI provider
- [ ] Complex tasks route to strongest available CLI provider
- [ ] CLIQuotaTracker.is_available() returns False for blocked providers and providers with >50% failure rate (≥3 sessions)
- [ ] CLIQuotaTracker tracks last_health_check, last_error, last_success_at, last_failure_at
- [ ] ContextOptimizer uses adaptive max_context_tokens by budget tier (low: 2k-4k, medium: 4k-8k, high: up to 16k)
- [ ] Context trimming priority: REQUIRED > RELEVANT > OPTIONAL
- [ ] /api/system/stats shows provider-level breakdown with adaptive signals
- [ ] No silent paid API fallback under any condition
- [ ] All Phase 1-5.5 regression tests still pass
- [ ] No new tables — all changes are additive columns only

## Future Work (Documented, Not Implemented)

- **Execution layer retry/fallback:** Worker/orchestrator reads RoutingDecision and iterates through considered_providers on failure, with model tier escalation (max 2 retries)
- **Ollama-style local models:** Add a local model provider for $0 cost tasks
- **Provider benchmarking:** Runtime benchmarks to auto-select fastest provider
- **Streaming events:** Structured streaming event protocol (inspired by openclaude)
- **Permission workflow:** Richer action_required workflow with user approval chain
- **Provider health scoring:** Weighted scoring based on recent success/failure rate over longer windows
