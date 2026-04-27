# Phase 3B: Adaptive Model Routing + Quota/Budget Manager + Provider Adapter

**Date:** 2026-04-24
**Status:** Design In Progress
**Phase:** 3B

---

## 1. Overview

Before connecting real AI agents, ORKA must learn how to choose the right model for the right task, track usage, respect quota limits, and fall back safely — without creating unexpected charges.

This phase introduces:
- Provider adapter interface (OpenAI-compatible + OpenRouter)
- Task classification and model routing
- **Quota Manager** — provider quota tracking (plan allowances, time windows, token limits)
- **Budget Manager** — USD cost limits for paid API usage
- Usage tracking and routing decision logs
- Simulation-first mode with optional LLM activation

**Core principle: quota-only by default.** The system must never silently switch to paid usage. Paid fallback requires explicit user approval.

---

## 2. Architecture

**Centralized Router pattern:**

```
Task / Agent Request
  → TaskClassifier (analyze complexity, importance, type)
  → QuotaManager check (is provider quota available?)
  → BudgetManager check (can we afford the ideal model?)
  → ModelRouter decision (pick best model within quota + budget)
  → ProviderAdapter execution (call LLM)
  → RoutingDecisionLog (record everything)
```

All routing decisions flow through a single `ModelRouter` service. Quota is checked before budget — quota-only is the default mode. Agent preferences are inputs to the router, not separate routing brains.

**Provider mode states:**

```
available       → quota available, provider healthy
throttled       → quota nearing limit, downgrading calls
quota_exhausted → quota fully consumed, waiting for reset
blocked_until_reset → hard-blocked with known reset time
unavailable     → provider down or not configured
```

---

## 3. Provider Adapter Interface

### 3.1 BaseProvider (Abstract)

```python
class BaseProvider(ABC):
    @abstractmethod
    async def complete(self, prompt, model, max_tokens, temperature) -> ProviderResponse

    @abstractmethod
    async def stream(self, prompt, model, **kwargs) -> AsyncIterator[str]

    @abstractmethod
    def get_models(self) -> list[ModelInfo]

    @abstractmethod
    async def health_check(self) -> bool

    @abstractmethod
    def estimate_cost(self, tokens: int, model: str) -> float
```

### 3.2 OpenAICompatProvider

Single adapter that works with any OpenAI-compatible endpoint. Configured via `base_url` and `api_key` env vars.

Supports: Claude API (via OpenAI compat), OpenAI, z.ai, Gemini — all connect through the same adapter with different base URLs.

### 3.3 OpenRouterProvider

Separate adapter for OpenRouter API. Acts as fallback/gateway when direct provider is unavailable.

### 3.4 ProviderRegistry

Config-driven. Reads from `providers.yaml` or environment variables to determine which providers are active.

**Key constraints:**
- API keys come only from backend environment variables
- Provider health checks are non-blocking (run async, don't block startup)
- Missing provider config = provider unavailable, not an error
- Direct Claude/non-OpenAI-native adapter support remains possible for future phases

---

## 4. Task Classifier + Model Registry

### 4.1 TaskClassifier

Analyzes a task and produces a `TaskProfile`:

```python
@dataclass
class TaskProfile:
    complexity: str       # "simple" | "medium" | "complex"
    importance: str       # "low" | "normal" | "critical"
    task_type: str        # "code_gen" | "analysis" | "docs" | "review" | "planning"
    context_size: int     # estimated tokens
    agent_type: str       # "backend" | "frontend" | "qa" | "docs" | "memory" | "orchestrator"
    budget_tier: str      # "low" | "medium" | "high" | "dynamic"
```

**Classification rules (config-driven):**

| Agent Type | Default Complexity | Budget Tier |
|---|---|---|
| docs / memory | simple | low |
| brainstorm / product | medium | medium |
| backend / QA / architecture | medium | high |
| orchestrator | dynamic | dynamic |

**Context-size-aware routing:**
- If task context exceeds low-tier model limits, auto-upgrade to medium
- If context exceeds medium-tier limits, auto-upgrade to high
- Large context tasks never use low-tier models

**Model strengths matching (optional):**
- Code tasks → prefer models with "code" strength
- Analysis tasks → prefer models with "reasoning" strength
- This is a tiebreaker, not a primary routing factor

### 4.2 ModelInfo

```python
@dataclass
class ModelInfo:
    id: str               # "gpt-4o", "claude-sonnet-4-6", "gemini-2.5-flash"
    provider: str         # "openai", "openrouter"
    tier: str             # "low" | "medium" | "high"
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_tokens: int
    strengths: list[str]  # ["code", "analysis", "reasoning"]
    speed: str            # "fast" | "medium" | "slow"
```

### 4.3 Model Mapping Table (config)

| Budget Tier | Default Model | Fallback |
|---|---|---|
| low | gemini-2.5-flash | gpt-4o-mini |
| medium | claude-sonnet-4-6 | gpt-4o |
| high | claude-opus-4-7 | gpt-4o |
| dynamic | claude-sonnet-4-6 | context-dependent |

---

## 5. Quota Manager

### 5.1 Provider Quota Profiles

Each provider/model source defines a quota profile:

```python
@dataclass
class ProviderQuotaProfile:
    provider: str
    quota_type: str           # "time_window" | "token_limit" | "request_limit" | "manual"
    window_duration: int | None    # seconds (e.g. 18000 = 5 hours)
    weekly_limit: float | None     # token/request count if applicable
    reset_at: datetime | None      # known reset timestamp
    remaining_quota: float | None  # estimated remaining allowance
    allow_paid_overage: bool = False  # NEVER true by default
```

**Quota types:**

| Type | Description | Example |
|---|---|---|
| `time_window` | Usage resets after fixed duration | Claude Code 5-hour window |
| `token_limit` | Fixed token allowance per period | OpenRouter free tier |
| `request_limit` | Fixed request count per period | API free plan |
| `manual` | User manages quota externally | Self-hosted endpoints |

### 5.2 Quota State Machine

Each provider tracks its own quota state independently:

```
AVAILABLE (remaining > threshold)
  → Full access to provider models
  │
  │ remaining <= threshold
  ▼
THROTTLED (remaining > 0)
  → Reduce call frequency, prefer cheaper models on this provider
  → Log throttle reason
  │
  │ remaining <= 0
  ▼
EXHAUSTED (no remaining quota)
  → Block all calls to this provider
  → If reset_at known: show "Provider quota exhausted. Resumes at [time]"
  → If reset_at unknown: show "Provider quota exhausted. Manual reset required."
  │
  │ reset_at reached
  ▼
AVAILABLE (quota refreshed)
```

### 5.3 Quota Tracking

**Usage estimation per call:**
- Before call: estimate token usage from prompt + max_tokens
- After call: record actual input_tokens + output_tokens
- Deduct from `remaining_quota` in real-time

**Provider-specific behaviors:**

**Claude Code / plan-based:**
- Track active usage windows (start time, estimated allowance)
- Track cumulative estimated tokens consumed in current window
- Detect quota/rate-limit signals from CLI output (if applicable)
- When quota reached: set `blocked_until = reset_at`, mark provider as `quota_exhausted`
- Display: "Claude Code quota is exhausted. It will resume at [time]."

**OpenRouter:**
- Track token counts against known free-tier limits
- Respect rate-limit headers from API responses
- If paid tier not enabled, never exceed free allowance

**API-key providers (OpenAI, z.ai, Gemini):**
- Track token usage per billing period if pricing is known
- Or operate in `manual` quota mode — user manages externally

### 5.4 Quota-Aware Routing

ModelRouter checks quota before selecting provider/model:

```
1. Identify candidate providers for the requested model/tier
2. For each candidate, check QuotaManager:
   - If AVAILABLE → eligible
   - If THROTTLED → eligible but prefer alternatives
   - If EXHAUSTED → skip provider
3. If at least one eligible provider → proceed with best match
4. If no eligible provider:
   - Check if any free/allowed provider exists for a lower tier model
   - If yes → downgrade and log
   - If no → pause task, show "Action required: all providers exhausted"
```

### 5.5 No Surprise Paid Fallback

**Strict rules — no exceptions:**

1. If a provider quota is exhausted, do NOT automatically use paid API on another provider
2. Do NOT charge any provider with `allow_paid_overage: false` beyond its quota
3. Fallback only to providers that have remaining quota AND are explicitly allowed
4. Paid fallback requires user action:
   - Dashboard shows "All free quota exhausted. Enable paid fallback for [provider]?"
   - User must explicitly approve
   - Decision is logged with timestamp and reason
5. `ALLOW_PAID_OVERAGE=false` is the default for every provider

### 5.6 Critical Override

When quota is exhausted and a critical task (`importance: critical`) exists:

1. Check if any provider has remaining quota (even throttled)
2. If none: ask user explicitly — "Critical task pending but all providers are exhausted. Approve paid fallback?"
3. User approval → allow single paid call, log the decision
4. Never enable paid fallback silently — always require explicit per-incident approval

---

## 6. Budget Manager

Budget Manager runs alongside Quota Manager. It applies USD-based limits for providers where paid usage is explicitly enabled.

### 6.1 BudgetConfig

```python
@dataclass
class BudgetConfig:
    daily_soft_limit: float      # USD (default: 5.0)
    daily_hard_limit: float      # USD (default: 10.0)
    monthly_hard_limit: float    # USD (default: 100.0)
    per_task_max_cost: float     # USD (default: 1.0)
```

All values are configurable via environment variables or API. Safe defaults allow the app to boot without setup.

### 6.2 Budget State Machine

Only active for paid usage (when quota is exhausted AND paid overage is explicitly allowed):

```
NORMAL (daily_spend < soft_limit)
  → Any model allowed
  │
  │ spend >= soft_limit
  ▼
THROTTLED (soft_limit <= spend < hard_limit)
  → Only low/medium tier models
  │
  │ spend >= hard_limit
  ▼
BLOCKED (spend >= hard_limit)
  → Non-critical calls blocked
  → Critical tasks may proceed with explicit logged reason
  → User approval required for any call
```

### 6.3 Fallback Chain

1. Primary model call fails (provider down) → try same model on another provider with available quota
2. Provider quota exhausted → select one tier lower model from a provider with quota
3. All providers quota-exhausted → check if any paid provider is explicitly allowed
4. No allowed providers → pause task, show action required
5. Hard budget limit reached (for paid providers) → only `importance: critical` tasks run with user approval

**All fallbacks and downgrades are logged in RoutingDecisionLog.**

### 6.4 Usage Tracking

Every API call logs:
- `provider`, `model`, `input_tokens`, `output_tokens`
- `cost_usd`, `latency_ms`
- `task_id`, `agent_type`
- `routing_decision_id`
- `quota_consumed` (tokens deducted from provider quota)

`UsageRecord` stored in database. Dashboard shows basic daily/monthly spend summaries + quota status.

---

## 7. Routing Decision Log

Every routing decision is recorded:

```python
class RoutingDecision:
    id: str
    task_id: str
    agent_type: str
    requested_tier: str
    selected_model: str
    selected_provider: str
    reason: str              # "auto" | "quota_throttle" | "budget_throttle" | "manual_override"
                             # | "fallback_quota_exhausted" | "fallback_provider_down" | "paid_override_approved"
    fallback_from: str | None  # original model/provider if fallback happened
    quota_status: str          # "available" | "throttled" | "exhausted" | "paid_override"
    cost_estimate: float
    actual_cost: float | None
    blocked_reason: str | None # "quota_exhausted" | "budget_exhausted" | "no_provider"
    created_at: datetime
```

---

## 8. API Endpoints

### Model & Provider Management
```
GET  /api/models              # List all known models
GET  /api/models/available    # Models from active providers (with quota status)
GET  /api/providers           # Registered providers + health + quota status
```

### Quota Management
```
GET  /api/quota/status        # All providers: quota state, remaining, reset_at
GET  /api/quota/{provider}    # Single provider quota detail
POST /api/quota/{provider}/reset  # Manual quota reset (for manual quota_type)
```

### Budget Management
```
GET  /api/budget/status       # Daily/monthly spend status
PUT  /api/budget/config       # Update limits
GET  /api/budget/usage        # Usage history (filterable by date, agent, model, provider)
```

### Routing Decisions
```
GET  /api/routing/decisions          # Recent routing decisions
GET  /api/routing/decisions/{id}     # Single decision detail
```

### Task Override
```
POST /api/tasks/{id}/model-override  # Manual model selection (optional, advanced)
```

### Paid Fallback Approval
```
POST /api/quota/paid-override/approve  # Approve one-time paid fallback for critical task
```

---

## 9. Database Models

```python
class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: str
    task_id: str | None
    agent_type: str | None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    routing_decision_id: str | None
    created_at: datetime

class RoutingDecision(Base):
    __tablename__ = "routing_decisions"
    id: str
    task_id: str | None
    agent_type: str | None
    requested_tier: str
    selected_model: str
    selected_provider: str
    reason: str
    fallback_from: str | None
    quota_status: str
    cost_estimate: float
    actual_cost: float | None
    blocked_reason: str | None
    created_at: datetime

class BudgetConfigDB(Base):
    __tablename__ = "budget_configs"
    id: str
    daily_soft_limit: float
    daily_hard_limit: float
    monthly_hard_limit: float
    per_task_max_cost: float
    updated_at: datetime

class ProviderQuotaState(Base):
    __tablename__ = "provider_quota_states"
    id: str
    provider: str             # unique per provider
    quota_type: str           # "time_window" | "token_limit" | "request_limit" | "manual"
    status: str               # "available" | "throttled" | "exhausted"
    remaining_quota: float | None
    total_quota: float | None
    window_started_at: datetime | None
    reset_at: datetime | None
    allow_paid_overage: bool  # default: false
    updated_at: datetime
```

---

## 10. Simulation-First Mode

**Critical design principle:** ORKA must work without any provider configured.

### 10.1 Mode Toggle

Environment variable `ORKA_LLM_ENABLED`:
- `false` (default) → all agent calls use existing simulation
- `true` → agent calls go through ModelRouter → ProviderAdapter → real LLM

### 10.2 Graceful Degradation

- No API key configured → simulation mode continues
- Provider unavailable at startup → marked unavailable, simulation fallback
- Provider fails mid-call → logged, fallback to simulation or alternative provider
- All providers quota-exhausted → task paused, user notified, simulation NOT auto-enabled
- App never crashes due to missing provider configuration

### 10.3 Integration Points

1. `AgentSimulator.process_task()` → checks `ORKA_LLM_ENABLED` flag
   - If false: existing simulation behavior (unchanged)
   - If true: delegates to ModelRouter for real LLM call
2. `BrainstormAgent` → same toggle applies
3. Task distribution → model routing decisions generated only in LLM mode

---

## 11. Frontend Components (Phase 3B Minimum)

Backend correctness is prioritized. Frontend gets minimal UI:

- **QuotaStatus** — provider cards showing: quota mode (available/throttled/exhausted), remaining quota, reset_at time, blocked_until
- **BudgetStatus** — small widget on dashboard showing daily/monthly spend
- **ModelIndicator** — task card shows which model was used (or "simulated")
- **RoutingLog** — simple table showing recent routing decisions with quota/budget reasons
- **PaidOverridePrompt** — modal for approving one-time paid fallback on critical tasks

Dashboard charts and detailed analytics deferred to a later phase.

---

## 12. Configuration

### Environment Variables

```env
# Mode
ORKA_LLM_ENABLED=false
DEFAULT_AI_MODE=quota_only

# Provider fallback policy
ALLOW_PAID_OVERAGE=false
PROVIDER_FALLBACK_POLICY=free_or_approved_only

# Providers (all optional)
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENROUTER_API_KEY=
ZAI_API_KEY=
ZAI_BASE_URL=
GEMINI_API_KEY=
GEMINI_BASE_URL=

# Quota profiles (per provider)
CLAUDE_CODE_QUOTA_TYPE=time_window
CLAUDE_CODE_WINDOW_DURATION=18000
CLAUDE_CODE_WEEKLY_LIMIT=
CLAUDE_CODE_ALLOW_PAID_OVERAGE=false

OPENROUTER_QUOTA_TYPE=token_limit
OPENROUTER_WEEKLY_LIMIT=1000000
OPENROUTER_ALLOW_PAID_OVERAGE=false

# Budget defaults (for paid usage when explicitly enabled)
ORKA_DAILY_SOFT_LIMIT=5.0
ORKA_DAILY_HARD_LIMIT=10.0
ORKA_MONTHLY_HARD_LIMIT=100.0
ORKA_PER_TASK_MAX_COST=1.0

# Default provider for each tier
ORKA_LOW_TIER_MODEL=gemini-2.5-flash
ORKA_MEDIUM_TIER_MODEL=claude-sonnet-4-6
ORKA_HIGH_TIER_MODEL=claude-opus-4-7
```

---

## 13. File Structure

```
backend/app/
├── providers/
│   ├── __init__.py
│   ├── base.py              # BaseProvider abstract class
│   ├── openai_compat.py     # OpenAI-compatible adapter
│   ├── openrouter.py        # OpenRouter adapter
│   └── registry.py          # Provider registration and management
├── services/
│   ├── model_router.py      # Central routing logic
│   ├── task_classifier.py   # Task analysis → TaskProfile
│   ├── quota_manager.py     # Quota tracking, state machine, provider quota profiles
│   ├── budget_manager.py    # USD budget state machine + tracking
│   ├── model_registry.py    # Model info + mapping table
│   └── usage_tracker.py     # Usage recording
├── api/
│   ├── models.py            # Model/provider endpoints
│   ├── quota.py             # Quota status + reset endpoints
│   ├── budget.py            # Budget endpoints
│   └── routing.py           # Routing decision endpoints
└── config/
    └── model_config.py      # Configuration loading (env + defaults)
```

---

## 14. Scope Boundaries

**In scope (Phase 3B):**
- Provider adapter interface with OpenAI-compat + OpenRouter
- Task classifier with config-driven rules
- Model registry with mapping table
- Centralized model router (quota-first, then budget)
- Quota manager (provider quota profiles, state machine, tracking)
- Budget manager (USD limits, state machine — only for explicitly enabled paid usage)
- No-surprise-paid-fallback enforcement
- Usage tracking and routing decision logging
- API endpoints for models, quota, budget, routing
- Simulation-first mode toggle
- Minimal frontend components (quota status, budget status, model indicator, routing log, paid override prompt)

**Out of scope (future phases):**
- Agent-to-agent real messaging
- Streaming responses in frontend
- Dashboard analytics charts
- Direct non-OpenAI-compatible provider adapters (e.g., native Claude SDK)
- Model fine-tuning or custom endpoints
- Multi-user budget management
- Automated quota detection from provider APIs (manual config for Phase 3B)
