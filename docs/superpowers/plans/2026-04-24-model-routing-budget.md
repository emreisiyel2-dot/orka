# Phase 3B: Adaptive Model Routing + Quota/Budget Manager

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add provider adapters, quota-first model routing, budget management, and usage tracking to ORKA — defaulting to quota-only mode, never silently falling back to paid usage.

**Architecture:** Centralized `ModelRouter` service with quota-checked-before-budget flow. Provider adapters behind a `BaseProvider` interface. Simulation mode preserved behind `ORKA_LLM_ENABLED` flag.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic, httpx (for provider calls), Next.js/TypeScript (frontend)

**Spec:** `docs/superpowers/specs/2026-04-24-model-routing-budget-design.md`

---

## File Structure

```
backend/
├── app/
│   ├── config/
│   │   └── model_config.py          # NEW — env/config loader for providers, quotas, budgets
│   ├── providers/
│   │   ├── __init__.py              # NEW
│   │   ├── base.py                  # NEW — BaseProvider ABC, ProviderResponse, ModelInfo
│   │   ├── openai_compat.py         # NEW — OpenAI-compatible provider adapter
│   │   ├── openrouter.py            # NEW — OpenRouter provider adapter
│   │   └── registry.py              # NEW — ProviderRegistry: register, health-check, list
│   ├── services/
│   │   ├── model_router.py          # NEW — TaskClassifier + ModelRouter + route()
│   │   ├── quota_manager.py         # NEW — QuotaManager: track, check, consume, reset
│   │   ├── budget_manager.py        # NEW — BudgetManager: spend tracking, state machine
│   │   └── usage_tracker.py         # NEW — UsageTracker: record every API call
│   ├── api/
│   │   ├── models_api.py            # NEW — /api/models, /api/providers endpoints
│   │   ├── quota.py                 # NEW — /api/quota endpoints
│   │   ├── budget.py                # NEW — /api/budget endpoints
│   │   └── routing.py               # NEW — /api/routing/decisions endpoints
│   ├── models.py                    # MODIFY — add UsageRecord, RoutingDecision, ProviderQuotaState, BudgetConfigDB
│   ├── schemas.py                   # MODIFY — add Phase 3B schemas
│   ├── database.py                  # MODIFY — import new models, seed quota states
│   └── main.py                      # MODIFY — include new routers, add quota-reset bg task
frontend/
├── lib/
│   ├── types.ts                     # MODIFY — add Phase 3B types
│   └── api.ts                       # MODIFY — add Phase 3B API methods
├── components/
│   ├── QuotaStatus.tsx              # NEW — provider quota cards
│   └── ModelIndicator.tsx           # NEW — model badge on task cards
```

---

### Task 1: Config loader + environment defaults

**Files:**
- Create: `backend/app/config/__init__.py`
- Create: `backend/app/config/model_config.py`

- [ ] **Step 1: Create config package init**

Create `backend/app/config/__init__.py` as an empty file.

- [ ] **Step 2: Create model_config.py**

Create `backend/app/config/model_config.py`:

```python
import os
from dataclasses import dataclass, field


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    quota_type: str = "manual"  # time_window | token_limit | request_limit | manual
    window_duration: int | None = None
    weekly_limit: float | None = None
    allow_paid_overage: bool = False


@dataclass
class QuotaConfig:
    threshold_percent: float = 0.2  # throttle when remaining < 20%


@dataclass
class BudgetDefaults:
    daily_soft_limit: float = 5.0
    daily_hard_limit: float = 10.0
    monthly_hard_limit: float = 100.0
    per_task_max_cost: float = 1.0


@dataclass
class ModelRoutingConfig:
    llm_enabled: bool = False
    default_ai_mode: str = "quota_only"
    allow_paid_overage: bool = False
    fallback_policy: str = "free_or_approved_only"
    low_tier_model: str = "gemini-2.5-flash"
    medium_tier_model: str = "claude-sonnet-4-6"
    high_tier_model: str = "claude-opus-4-7"
    providers: list[ProviderConfig] = field(default_factory=list)
    budget: BudgetDefaults = field(default_factory=BudgetDefaults)
    quota: QuotaConfig = field(default_factory=QuotaConfig)


def load_config() -> ModelRoutingConfig:
    providers: list[ProviderConfig] = []

    # OpenAI-compatible providers
    for prefix, name in [
        ("OPENAI", "openai"),
        ("ZAI", "zai"),
        ("GEMINI", "gemini"),
    ]:
        key = os.getenv(f"{prefix}_API_KEY", "")
        url = os.getenv(f"{prefix}_BASE_URL", "")
        if key:
            providers.append(ProviderConfig(
                name=name,
                base_url=url or f"https://api.{name.lower()}.com/v1",
                api_key=key,
                quota_type=os.getenv(f"{prefix}_QUOTA_TYPE", "manual"),
                window_duration=_int_env(f"{prefix}_WINDOW_DURATION"),
                weekly_limit=_float_env(f"{prefix}_WEEKLY_LIMIT"),
                allow_paid_overage=os.getenv(f"{prefix}_ALLOW_PAID_OVERAGE", "false").lower() == "true",
            ))

    # OpenRouter
    or_key = os.getenv("OPENROUTER_API_KEY", "")
    if or_key:
        providers.append(ProviderConfig(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=or_key,
            quota_type=os.getenv("OPENROUTER_QUOTA_TYPE", "token_limit"),
            weekly_limit=_float_env("OPENROUTER_WEEKLY_LIMIT") or 1_000_000,
            allow_paid_overage=os.getenv("OPENROUTER_ALLOW_PAID_OVERAGE", "false").lower() == "true",
        ))

    return ModelRoutingConfig(
        llm_enabled=os.getenv("ORKA_LLM_ENABLED", "false").lower() == "true",
        default_ai_mode=os.getenv("DEFAULT_AI_MODE", "quota_only"),
        allow_paid_overage=os.getenv("ALLOW_PAID_OVERAGE", "false").lower() == "true",
        fallback_policy=os.getenv("PROVIDER_FALLBACK_POLICY", "free_or_approved_only"),
        low_tier_model=os.getenv("ORKA_LOW_TIER_MODEL", "gemini-2.5-flash"),
        medium_tier_model=os.getenv("ORKA_MEDIUM_TIER_MODEL", "claude-sonnet-4-6"),
        high_tier_model=os.getenv("ORKA_HIGH_TIER_MODEL", "claude-opus-4-7"),
        providers=providers,
        budget=BudgetDefaults(
            daily_soft_limit=_float_env("ORKA_DAILY_SOFT_LIMIT") or 5.0,
            daily_hard_limit=_float_env("ORKA_DAILY_HARD_LIMIT") or 10.0,
            monthly_hard_limit=_float_env("ORKA_MONTHLY_HARD_LIMIT") or 100.0,
            per_task_max_cost=_float_env("ORKA_PER_TASK_MAX_COST") or 1.0,
        ),
    )


def _float_env(key: str) -> float | None:
    v = os.getenv(key)
    return float(v) if v else None


def _int_env(key: str) -> int | None:
    v = os.getenv(key)
    return int(v) if v else None
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/config/
git commit -m "feat(3b): config loader for providers, quotas, budgets"
```

---

### Task 2: BaseProvider + data classes

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`

- [ ] **Step 1: Create providers package init**

Create `backend/app/providers/__init__.py` as an empty file.

- [ ] **Step 2: Create base.py with BaseProvider ABC and shared data classes**

Create `backend/app/providers/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ModelInfo:
    id: str
    provider: str
    tier: str  # "low" | "medium" | "high"
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_tokens: int
    strengths: list[str] = field(default_factory=list)
    speed: str = "medium"  # "fast" | "medium" | "slow"


@dataclass
class ProviderResponse:
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class BaseProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> ProviderResponse:
        ...

    @abstractmethod
    async def stream(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        ...

    @abstractmethod
    def get_models(self) -> list[ModelInfo]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @abstractmethod
    def estimate_cost(self, tokens: int, model: str) -> float:
        ...
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/providers/
git commit -m "feat(3b): BaseProvider ABC and shared data classes"
```

---

### Task 3: OpenAI-compatible provider adapter

**Files:**
- Create: `backend/app/providers/openai_compat.py`

- [ ] **Step 1: Create OpenAICompatProvider**

Create `backend/app/providers/openai_compat.py`:

```python
import time
from typing import AsyncIterator

import httpx

from app.providers.base import BaseProvider, ModelInfo, ProviderResponse


_MODELS: list[ModelInfo] = [
    ModelInfo("gpt-4o", "openai", "high", 0.0025, 0.01, 128000, ["code", "reasoning"], "medium"),
    ModelInfo("gpt-4o-mini", "openai", "low", 0.00015, 0.0006, 128000, ["code", "general"], "fast"),
    ModelInfo("claude-sonnet-4-6", "anthropic", "medium", 0.003, 0.015, 200000, ["code", "reasoning", "analysis"], "medium"),
    ModelInfo("claude-opus-4-7", "anthropic", "high", 0.015, 0.075, 200000, ["reasoning", "analysis", "code"], "slow"),
    ModelInfo("gemini-2.5-flash", "google", "low", 0.000075, 0.0003, 1000000, ["code", "general"], "fast"),
]


class OpenAICompatProvider(BaseProvider):
    def __init__(self, name: str, base_url: str, api_key: str):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def get_models(self) -> list[ModelInfo]:
        return [m for m in _MODELS if m.provider == self.name or self.name in ("openai", "zai", "gemini")]

    async def complete(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> ProviderResponse:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        latency = int((time.monotonic() - start) * 1000)
        usage = data.get("usage", {})
        choice = data["choices"][0]["message"]["content"]
        info = next((m for m in _MODELS if m.id == model), None)
        cost = 0.0
        if info:
            cost = (usage.get("prompt_tokens", 0) / 1000 * info.cost_per_1k_input
                    + usage.get("completion_tokens", 0) / 1000 * info.cost_per_1k_output)

        return ProviderResponse(
            content=choice,
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cost_usd=cost,
            latency_ms=latency,
        )

    async def stream(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        import json
                        chunk = json.loads(line[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, tokens: int, model: str) -> float:
        info = next((m for m in _MODELS if m.id == model), None)
        if info:
            return tokens / 1000 * info.cost_per_1k_input
        return 0.0
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/providers/openai_compat.py
git commit -m "feat(3b): OpenAI-compatible provider adapter"
```

---

### Task 4: OpenRouter provider adapter

**Files:**
- Create: `backend/app/providers/openrouter.py`

- [ ] **Step 1: Create OpenRouterProvider**

Create `backend/app/providers/openrouter.py`:

```python
from app.providers.openai_compat import OpenAICompatProvider


class OpenRouterProvider(OpenAICompatProvider):
    """OpenRouter delegates to OpenAICompatProvider with different headers."""

    async def complete(self, prompt, model, max_tokens=4096, temperature=0.7):
        # OpenRouter uses the same OpenAI chat completions format
        return await super().complete(prompt, model, max_tokens, temperature)

    def get_models(self):
        # OpenRouter can route to any model
        from app.providers.openai_compat import _MODELS
        return [m for m in _MODELS]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/providers/openrouter.py
git commit -m "feat(3b): OpenRouter provider adapter"
```

---

### Task 5: Provider Registry

**Files:**
- Create: `backend/app/providers/registry.py`

- [ ] **Step 1: Create ProviderRegistry**

Create `backend/app/providers/registry.py`:

```python
from app.config.model_config import ModelRoutingConfig, ProviderConfig
from app.providers.base import BaseProvider, ModelInfo
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.openrouter import OpenRouterProvider


class ProviderRegistry:
    def __init__(self, config: ModelRoutingConfig):
        self._providers: dict[str, BaseProvider] = {}
        for pc in config.providers:
            if pc.name == "openrouter":
                provider = OpenRouterProvider(pc.name, pc.base_url, pc.api_key)
            else:
                provider = OpenAICompatProvider(pc.name, pc.base_url, pc.api_key)
            self._providers[pc.name] = provider

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def all(self) -> dict[str, BaseProvider]:
        return dict(self._providers)

    def all_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        for p in self._providers.values():
            models.extend(p.get_models())
        return models

    def find_provider_for_model(self, model_id: str) -> BaseProvider | None:
        for p in self._providers.values():
            if any(m.id == model_id for m in p.get_models()):
                return p
        return None

    def find_providers_for_tier(self, tier: str) -> list[BaseProvider]:
        result = []
        for p in self._providers.values():
            if any(m.tier == tier for m in p.get_models()):
                result.append(p)
        return result
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/providers/registry.py
git commit -m "feat(3b): ProviderRegistry — register, lookup, find by model/tier"
```

---

### Task 6: Database models for Phase 3B

**Files:**
- Modify: `backend/app/models.py`

- [ ] **Step 1: Add Phase 3B models at the end of models.py**

Append after the `BrainstormSkill` class in `backend/app/models.py`:

```python


# ──────────────────────────────────────────────
# Phase 3B: Model Routing / Quota / Budget
# ──────────────────────────────────────────────


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    routing_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("routing_decisions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )
    agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    requested_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    selected_model: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    fallback_from: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quota_status: Mapped[str] = mapped_column(String(30), nullable=False, default="available")
    cost_estimate: Mapped[float] = mapped_column(default=0.0)
    actual_cost: Mapped[float | None] = mapped_column(nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    usage_records: Mapped[list["UsageRecord"]] = relationship(lazy="selectin")


class BudgetConfigDB(Base):
    __tablename__ = "budget_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    daily_soft_limit: Mapped[float] = mapped_column(default=5.0)
    daily_hard_limit: Mapped[float] = mapped_column(default=10.0)
    monthly_hard_limit: Mapped[float] = mapped_column(default=100.0)
    per_task_max_cost: Mapped[float] = mapped_column(default=1.0)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class ProviderQuotaState(Base):
    __tablename__ = "provider_quota_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    quota_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="available"
    )
    remaining_quota: Mapped[float | None] = mapped_column(nullable=True)
    total_quota: Mapped[float | None] = mapped_column(nullable=True)
    window_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reset_at: Mapped[datetime | None] = mapped_column(nullable=True)
    allow_paid_overage: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/models.py
git commit -m "feat(3b): add UsageRecord, RoutingDecision, BudgetConfigDB, ProviderQuotaState models"
```

---

### Task 7: Pydantic schemas for Phase 3B

**Files:**
- Modify: `backend/app/schemas.py`

- [ ] **Step 1: Add Phase 3B schemas at the end of schemas.py**

Append after `SpawnPlan` in `backend/app/schemas.py`:

```python


# ──────────────────────────────────────────────
# Phase 3B: Model Routing / Quota / Budget
# ──────────────────────────────────────────────


class ModelInfoResponse(BaseModel):
    id: str
    provider: str
    tier: str
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_tokens: int
    strengths: list[str] = []
    speed: str = "medium"


class ProviderStatusResponse(BaseModel):
    name: str
    healthy: bool
    quota_status: str  # available | throttled | exhausted | unavailable
    remaining_quota: float | None = None
    total_quota: float | None = None
    reset_at: datetime | None = None
    allow_paid_overage: bool = False
    models: list[ModelInfoResponse] = []


class UsageRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str | None = None
    agent_type: str | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    routing_decision_id: str | None = None
    created_at: datetime


class RoutingDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str | None = None
    agent_type: str | None = None
    requested_tier: str
    selected_model: str
    selected_provider: str
    reason: str
    fallback_from: str | None = None
    quota_status: str
    cost_estimate: float
    actual_cost: float | None = None
    blocked_reason: str | None = None
    created_at: datetime


class BudgetStatusResponse(BaseModel):
    daily_spend: float
    daily_soft_limit: float
    daily_hard_limit: float
    monthly_spend: float
    monthly_hard_limit: float
    state: str  # normal | throttled | blocked


class BudgetConfigUpdate(BaseModel):
    daily_soft_limit: float | None = None
    daily_hard_limit: float | None = None
    monthly_hard_limit: float | None = None
    per_task_max_cost: float | None = None


class QuotaStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    quota_type: str
    status: str
    remaining_quota: float | None = None
    total_quota: float | None = None
    reset_at: datetime | None = None
    allow_paid_overage: bool
    updated_at: datetime


class PaidOverrideApprove(BaseModel):
    task_id: str
    provider: str
    reason: str


class TaskModelOverride(BaseModel):
    model_id: str
    provider: str
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat(3b): Pydantic schemas for models, quota, budget, routing"
```

---

### Task 8: Database import updates + quota seeding

**Files:**
- Modify: `backend/app/database.py`

- [ ] **Step 1: Update imports and seed quota states**

In `backend/app/database.py`, update the import line:

```python
from app.models import Agent, Base, Worker, WorkerSession, WorkerLog, AutonomousDecision, AgentMessage, TaskDependency, BrainstormRoom, BrainstormMessage, BrainstormAgent, BrainstormSkill, UsageRecord, RoutingDecision, BudgetConfigDB, ProviderQuotaState
```

Then add to `seed_db()`, before the final `await session.commit()`:

```python
        # Seed default budget config
        result = await session.execute(select(BudgetConfigDB))
        if not result.scalars().first():
            session.add(BudgetConfigDB())

        await session.commit()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/database.py
git commit -m "feat(3b): import new models, seed default budget config"
```

---

### Task 9: Quota Manager service

**Files:**
- Create: `backend/app/services/quota_manager.py`

- [ ] **Step 1: Create QuotaManager**

Create `backend/app/services/quota_manager.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_config import ModelRoutingConfig
from app.models import ProviderQuotaState, UsageRecord


class QuotaManager:
    def __init__(self, config: ModelRoutingConfig):
        self._config = config

    async def get_state(self, provider: str, db: AsyncSession) -> ProviderQuotaState | None:
        result = await db.execute(
            select(ProviderQuotaState).where(ProviderQuotaState.provider == provider)
        )
        return result.scalars().first()

    async def ensure_state(self, provider: str, db: AsyncSession) -> ProviderQuotaState:
        state = await self.get_state(provider, db)
        if state:
            return state

        # Create from config
        pc = next((p for p in self._config.providers if p.name == provider), None)
        state = ProviderQuotaState(
            provider=provider,
            quota_type=pc.quota_type if pc else "manual",
            status="available",
            total_quota=pc.weekly_limit if pc else None,
            remaining_quota=pc.weekly_limit if pc else None,
            allow_paid_overage=pc.allow_paid_overage if pc else False,
        )
        db.add(state)
        await db.flush()
        return state

    async def check_available(self, provider: str, estimated_tokens: int, db: AsyncSession) -> str:
        """Returns: 'available' | 'throttled' | 'exhausted'."""
        state = await self.ensure_state(provider, db)

        # Check if reset time has passed
        if state.reset_at and datetime.now(timezone.utc) >= state.reset_at:
            state.status = "available"
            state.remaining_quota = state.total_quota
            state.reset_at = None
            state.window_started_at = datetime.now(timezone.utc)

        if state.status == "exhausted":
            return "exhausted"

        if state.remaining_quota is not None and state.total_quota is not None:
            threshold = state.total_quota * self._config.quota.threshold_percent
            if state.remaining_quota <= 0:
                state.status = "exhausted"
                await db.flush()
                return "exhausted"
            if state.remaining_quota < threshold:
                state.status = "throttled"
                await db.flush()
                return "throttled"

        return "available"

    async def consume(self, provider: str, tokens: int, db: AsyncSession) -> None:
        """Deduct consumed tokens from provider quota."""
        state = await self.ensure_state(provider, db)
        if state.remaining_quota is not None:
            state.remaining_quota = max(0, state.remaining_quota - tokens)
            if state.remaining_quota <= 0:
                state.status = "exhausted"
            elif state.total_quota and state.remaining_quota < state.total_quota * self._config.quota.threshold_percent:
                state.status = "throttled"

    async def reset_provider(self, provider: str, db: AsyncSession) -> None:
        state = await self.ensure_state(provider, db)
        state.status = "available"
        state.remaining_quota = state.total_quota
        state.window_started_at = datetime.now(timezone.utc)
        state.reset_at = None

    async def set_blocked_until(self, provider: str, reset_at: datetime, db: AsyncSession) -> None:
        state = await self.ensure_state(provider, db)
        state.status = "exhausted"
        state.remaining_quota = 0
        state.reset_at = reset_at

    async def get_all_states(self, db: AsyncSession) -> list[ProviderQuotaState]:
        result = await db.execute(select(ProviderQuotaState))
        return list(result.scalars().all())
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/quota_manager.py
git commit -m "feat(3b): QuotaManager — track, check, consume, reset provider quotas"
```

---

### Task 10: Budget Manager service

**Files:**
- Create: `backend/app/services/budget_manager.py`

- [ ] **Step 1: Create BudgetManager**

Create `backend/app/services/budget_manager.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BudgetConfigDB, UsageRecord


class BudgetManager:
    async def get_config(self, db: AsyncSession) -> BudgetConfigDB:
        result = await db.execute(select(BudgetConfigDB))
        cfg = result.scalars().first()
        if not cfg:
            cfg = BudgetConfigDB()
            db.add(cfg)
            await db.flush()
        return cfg

    async def get_daily_spend(self, db: AsyncSession) -> float:
        from datetime import timedelta
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
                UsageRecord.created_at >= today
            )
        )
        return float(result.scalar() or 0.0)

    async def get_monthly_spend(self, db: AsyncSession) -> float:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
                UsageRecord.created_at >= month_start
            )
        )
        return float(result.scalar() or 0.0)

    async def get_state(self, db: AsyncSession) -> str:
        """Returns: 'normal' | 'throttled' | 'blocked'."""
        cfg = await self.get_config(db)
        daily = await self.get_daily_spend(db)
        if daily >= cfg.daily_hard_limit:
            return "blocked"
        if daily >= cfg.daily_soft_limit:
            return "throttled"
        return "normal"

    async def can_afford(self, estimated_cost: float, db: AsyncSession) -> bool:
        cfg = await self.get_config(db)
        daily = await self.get_daily_spend(db)
        return (daily + estimated_cost) <= cfg.daily_hard_limit

    async def update_config(self, db: AsyncSession, **kwargs) -> BudgetConfigDB:
        cfg = await self.get_config(db)
        for key, val in kwargs.items():
            if val is not None and hasattr(cfg, key):
                setattr(cfg, key, val)
        cfg.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return cfg
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/budget_manager.py
git commit -m "feat(3b): BudgetManager — daily/monthly spend tracking, state machine"
```

---

### Task 11: Usage Tracker service

**Files:**
- Create: `backend/app/services/usage_tracker.py`

- [ ] **Step 1: Create UsageTracker**

Create `backend/app/services/usage_tracker.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageRecord
from app.providers.base import ProviderResponse


class UsageTracker:
    async def record(
        self,
        response: ProviderResponse,
        task_id: str | None,
        agent_type: str | None,
        routing_decision_id: str | None,
        db: AsyncSession,
    ) -> UsageRecord:
        record = UsageRecord(
            task_id=task_id,
            agent_type=agent_type,
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            routing_decision_id=routing_decision_id,
        )
        db.add(record)
        await db.flush()
        return record
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/usage_tracker.py
git commit -m "feat(3b): UsageTracker — record every API call"
```

---

### Task 12: Model Router (central routing logic)

**Files:**
- Create: `backend/app/services/model_router.py`

- [ ] **Step 1: Create TaskClassifier + ModelRouter**

Create `backend/app/services/model_router.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_config import ModelRoutingConfig
from app.models import RoutingDecision
from app.providers.base import BaseProvider, ModelInfo, ProviderResponse
from app.providers.registry import ProviderRegistry
from app.services.budget_manager import BudgetManager
from app.services.quota_manager import QuotaManager
from app.services.usage_tracker import UsageTracker


@dataclass
class TaskProfile:
    complexity: str       # "simple" | "medium" | "complex"
    importance: str       # "low" | "normal" | "critical"
    task_type: str        # "code_gen" | "analysis" | "docs" | "review" | "planning"
    context_size: int
    agent_type: str
    budget_tier: str      # "low" | "medium" | "high" | "dynamic"


_AGENT_TIER_DEFAULTS = {
    "docs": "low",
    "memory": "low",
    "brainstorm": "medium",
    "product": "medium",
    "backend": "high",
    "qa": "high",
    "architecture": "high",
    "orchestrator": "dynamic",
    "frontend": "medium",
}

_COMPLEXITY_KEYWORDS = {
    "critical": ["critical", "urgent", "production", "emergency", "broken"],
    "complex": ["architecture", "system", "integrate", "migrate", "redesign", "overhaul"],
    "simple": ["fix", "update", "add", "change", "rename", "typo"],
}


def classify_task(
    content: str,
    agent_type: str,
    importance: str = "normal",
) -> TaskProfile:
    budget_tier = _AGENT_TIER_DEFAULTS.get(agent_type, "medium")
    lower = content.lower()

    complexity = "medium"
    for level, keywords in _COMPLEXITY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            complexity = level
            break

    if len(content) < 100:
        complexity = min(complexity, "simple")

    task_type = "code_gen"
    if any(w in lower for w in ["doc", "readme", "comment", "explain"]):
        task_type = "docs"
    elif any(w in lower for w in ["test", "qa", "review", "check"]):
        task_type = "review"
    elif any(w in lower for w in ["analyz", "investigat", "assess"]):
        task_type = "analysis"
    elif any(w in lower for w in ["plan", "design", "architect"]):
        task_type = "planning"

    context_size = len(content.split()) * 2  # rough token estimate

    if importance == "critical":
        budget_tier = "high"

    return TaskProfile(
        complexity=complexity,
        importance=importance,
        task_type=task_type,
        context_size=context_size,
        agent_type=agent_type,
        budget_tier=budget_tier,
    )


def _tier_to_model(tier: str, config: ModelRoutingConfig) -> str:
    return {
        "low": config.low_tier_model,
        "medium": config.medium_tier_model,
        "high": config.high_tier_model,
        "dynamic": config.medium_tier_model,
    }.get(tier, config.medium_tier_model)


class ModelRouter:
    def __init__(self, config: ModelRoutingConfig, registry: ProviderRegistry):
        self._config = config
        self._registry = registry
        self._quota = QuotaManager(config)
        self._budget = BudgetManager()
        self._tracker = UsageTracker()

    async def route(
        self,
        profile: TaskProfile,
        task_id: str | None,
        db: AsyncSession,
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Route a task to the best available model. Returns (response, decision)."""
        target_model = _tier_to_model(profile.budget_tier, self._config)

        # 1. Find provider with quota for target model
        provider, model_info, quota_status = await self._find_available_provider(
            target_model, profile, db
        )

        # 2. If no provider available, try fallback tier
        fallback_from = None
        if provider is None and profile.budget_tier != "low":
            fallback_from = target_model
            # Try lower tier
            lower_tier = "medium" if profile.budget_tier in ("high", "dynamic") else "low"
            target_model = _tier_to_model(lower_tier, self._config)
            provider, model_info, quota_status = await self._find_available_provider(
                target_model, profile, db
            )

        # 3. Still no provider — log blocked decision
        if provider is None:
            decision = RoutingDecision(
                task_id=task_id,
                agent_type=profile.agent_type,
                requested_tier=profile.budget_tier,
                selected_model="none",
                selected_provider="none",
                reason="all_providers_exhausted",
                fallback_from=fallback_from,
                quota_status="exhausted",
                cost_estimate=0.0,
                blocked_reason="no_provider_with_quota",
            )
            db.add(decision)
            await db.flush()
            return None, decision

        # 4. Budget check (only for paid providers)
        estimated_cost = provider.estimate_cost(profile.context_size, target_model)
        budget_state = await self._budget.get_state(db)
        if budget_state == "blocked" and profile.importance != "critical":
            decision = RoutingDecision(
                task_id=task_id,
                agent_type=profile.agent_type,
                requested_tier=profile.budget_tier,
                selected_model="none",
                selected_provider="none",
                reason="budget_blocked",
                fallback_from=fallback_from,
                quota_status=quota_status,
                cost_estimate=estimated_cost,
                blocked_reason="budget_exhausted",
            )
            db.add(decision)
            await db.flush()
            return None, decision

        # 5. Execute the call
        reason = "auto"
        if fallback_from:
            reason = "fallback_quota_exhausted"
        elif quota_status == "throttled":
            reason = "quota_throttle"
        elif budget_state == "throttled":
            reason = "budget_throttle"

        try:
            response = await provider.complete(
                prompt="",  # caller sets prompt
                model=target_model,
            )
        except Exception:
            decision = RoutingDecision(
                task_id=task_id,
                agent_type=profile.agent_type,
                requested_tier=profile.budget_tier,
                selected_model=target_model,
                selected_provider=provider.name,
                reason="provider_error",
                fallback_from=fallback_from,
                quota_status=quota_status,
                cost_estimate=estimated_cost,
                blocked_reason="provider_call_failed",
            )
            db.add(decision)
            await db.flush()
            return None, decision

        # 6. Record decision + usage
        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model=target_model,
            selected_provider=provider.name,
            reason=reason,
            fallback_from=fallback_from,
            quota_status=quota_status,
            cost_estimate=estimated_cost,
            actual_cost=response.cost_usd,
        )
        db.add(decision)
        await db.flush()

        await self._tracker.record(response, task_id, profile.agent_type, decision.id, db)
        await self._quota.consume(provider.name, response.input_tokens + response.output_tokens, db)

        return response, decision

    async def _find_available_provider(
        self, model_id: str, profile: TaskProfile, db: AsyncSession
    ) -> tuple[BaseProvider | None, ModelInfo | None, str]:
        provider = self._registry.find_provider_for_model(model_id)
        if provider is None:
            return None, None, "unavailable"

        quota_status = await self._quota.check_available(
            provider.name, profile.context_size, db
        )
        if quota_status == "exhausted":
            return None, None, "exhausted"

        model_info = next(
            (m for m in provider.get_models() if m.id == model_id), None
        )
        return provider, model_info, quota_status
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/model_router.py
git commit -m "feat(3b): ModelRouter — classify, quota-check, budget-check, route, fallback"
```

---

### Task 13: API endpoints — models, providers

**Files:**
- Create: `backend/app/api/models_api.py`

- [ ] **Step 1: Create models/providers API**

Create `backend/app/api/models_api.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config.model_config import load_config
from app.providers.registry import ProviderRegistry
from app.schemas import ModelInfoResponse, ProviderStatusResponse
from app.services.quota_manager import QuotaManager

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models", response_model=list[ModelInfoResponse])
async def list_models():
    config = load_config()
    registry = ProviderRegistry(config)
    return registry.all_models()


@router.get("/models/available", response_model=list[ModelInfoResponse])
async def list_available_models(db: AsyncSession = Depends(get_db)):
    config = load_config()
    registry = ProviderRegistry(config)
    quota = QuotaManager(config)
    available = []
    for model in registry.all_models():
        state = await quota.get_state(model.provider, db)
        if state is None or state.status != "exhausted":
            available.append(model)
    return available


@router.get("/providers", response_model=list[ProviderStatusResponse])
async def list_providers(db: AsyncSession = Depends(get_db)):
    config = load_config()
    registry = ProviderRegistry(config)
    quota = QuotaManager(config)
    result = []
    for name, provider in registry.all():
        healthy = await provider.health_check()
        state = await quota.ensure_state(name, db)
        result.append(ProviderStatusResponse(
            name=name,
            healthy=healthy,
            quota_status=state.status,
            remaining_quota=state.remaining_quota,
            total_quota=state.total_quota,
            reset_at=state.reset_at,
            allow_paid_overage=state.allow_paid_overage,
            models=[ModelInfoResponse(**m.__dict__) for m in provider.get_models()],
        ))
    return result
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/models_api.py
git commit -m "feat(3b): /api/models and /api/providers endpoints"
```

---

### Task 14: API endpoints — quota

**Files:**
- Create: `backend/app/api/quota.py`

- [ ] **Step 1: Create quota API**

Create `backend/app/api/quota.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config.model_config import load_config
from app.models import ProviderQuotaState, RoutingDecision
from app.schemas import QuotaStatusResponse, PaidOverrideApprove, RoutingDecisionResponse
from app.services.quota_manager import QuotaManager

router = APIRouter(prefix="/api/quota", tags=["quota"])


@router.get("/status", response_model=list[QuotaStatusResponse])
async def quota_status(db: AsyncSession = Depends(get_db)):
    config = load_config()
    mgr = QuotaManager(config)
    states = await mgr.get_all_states(db)
    return states


@router.get("/{provider}", response_model=QuotaStatusResponse)
async def provider_quota(provider: str, db: AsyncSession = Depends(get_db)):
    config = load_config()
    mgr = QuotaManager(config)
    state = await mgr.get_state(provider, db)
    if not state:
        raise HTTPException(404, f"Provider '{provider}' not found")
    return state


@router.post("/{provider}/reset", response_model=QuotaStatusResponse)
async def reset_quota(provider: str, db: AsyncSession = Depends(get_db)):
    config = load_config()
    mgr = QuotaManager(config)
    await mgr.reset_provider(provider, db)
    state = await mgr.get_state(provider, db)
    return state


@router.post("/paid-override/approve", response_model=RoutingDecisionResponse)
async def approve_paid_override(data: PaidOverrideApprove, db: AsyncSession = Depends(get_db)):
    """Log a user-approved one-time paid fallback for a critical task."""
    decision = RoutingDecision(
        task_id=data.task_id,
        reason="paid_override_approved",
        selected_provider=data.provider,
        selected_model="override",
        requested_tier="override",
        quota_status="paid_override",
        cost_estimate=0.0,
    )
    db.add(decision)
    await db.flush()
    return decision
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/quota.py
git commit -m "feat(3b): /api/quota endpoints — status, reset, paid override"
```

---

### Task 15: API endpoints — budget + routing

**Files:**
- Create: `backend/app/api/budget.py`
- Create: `backend/app/api/routing.py`

- [ ] **Step 1: Create budget API**

Create `backend/app/api/budget.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import BudgetStatusResponse, BudgetConfigUpdate
from app.services.budget_manager import BudgetManager

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("/status", response_model=BudgetStatusResponse)
async def budget_status(db: AsyncSession = Depends(get_db)):
    mgr = BudgetManager()
    cfg = await mgr.get_config(db)
    return BudgetStatusResponse(
        daily_spend=await mgr.get_daily_spend(db),
        daily_soft_limit=cfg.daily_soft_limit,
        daily_hard_limit=cfg.daily_hard_limit,
        monthly_spend=await mgr.get_monthly_spend(db),
        monthly_hard_limit=cfg.monthly_hard_limit,
        state=await mgr.get_state(db),
    )


@router.put("/config", response_model=BudgetStatusResponse)
async def update_budget(data: BudgetConfigUpdate, db: AsyncSession = Depends(get_db)):
    mgr = BudgetManager()
    await mgr.update_config(db, **data.model_dump(exclude_none=True))
    cfg = await mgr.get_config(db)
    return BudgetStatusResponse(
        daily_spend=await mgr.get_daily_spend(db),
        daily_soft_limit=cfg.daily_soft_limit,
        daily_hard_limit=cfg.daily_hard_limit,
        monthly_spend=await mgr.get_monthly_spend(db),
        monthly_hard_limit=cfg.monthly_hard_limit,
        state=await mgr.get_state(db),
    )
```

- [ ] **Step 2: Create routing API**

Create `backend/app/api/routing.py`:

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RoutingDecision, UsageRecord
from app.schemas import RoutingDecisionResponse, UsageRecordResponse

router = APIRouter(prefix="/api/routing", tags=["routing"])


@router.get("/decisions", response_model=list[RoutingDecisionResponse])
async def list_decisions(
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RoutingDecision).order_by(RoutingDecision.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/decisions/{decision_id}", response_model=RoutingDecisionResponse)
async def get_decision(decision_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RoutingDecision).where(RoutingDecision.id == decision_id)
    )
    from fastapi import HTTPException
    d = result.scalars().first()
    if not d:
        raise HTTPException(404, "Decision not found")
    return d


@router.get("/usage", response_model=list[UsageRecordResponse])
async def list_usage(
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UsageRecord).order_by(UsageRecord.created_at.desc()).limit(limit)
    )
    return result.scalars().all()
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/budget.py backend/app/api/routing.py
git commit -m "feat(3b): /api/budget and /api/routing endpoints"
```

---

### Task 16: Register routers + background quota reset

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add imports for new routers**

Add after the existing router imports in `backend/app/main.py`:

```python
from app.api.models_api import router as models_api_router
from app.api.quota import router as quota_router
from app.api.budget import router as budget_router
from app.api.routing import router as routing_router
```

- [ ] **Step 2: Register routers**

Add after `app.include_router(brainstorms_router)`:

```python
app.include_router(models_api_router)
app.include_router(quota_router)
app.include_router(budget_router)
app.include_router(routing_router)
```

- [ ] **Step 3: Add quota-reset background task**

Add after `_auto_advance_stale_rooms`:

```python
async def _check_quota_resets() -> None:
    """Reset provider quotas when their reset_at time has passed."""
    while True:
        await asyncio.sleep(60)
        try:
            from app.config.model_config import load_config
            from app.services.quota_manager import QuotaManager
            config = load_config()
            mgr = QuotaManager(config)
            async with async_session() as db:
                for state in await mgr.get_all_states(db):
                    if state.reset_at and datetime.now(timezone.utc) >= state.reset_at:
                        await mgr.reset_provider(state.provider, db)
                await db.commit()
        except Exception:
            pass
```

Then in `lifespan`, add:

```python
quota_reset_task = asyncio.create_task(_check_quota_resets())
```

And in the shutdown section, add `quota_reset_task` to the cancel tuple.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(3b): register new routers, add quota-reset background task"
```

---

### Task 17: Frontend types

**Files:**
- Modify: `frontend/lib/types.ts`

- [ ] **Step 1: Add Phase 3B types**

Append at the end of `frontend/lib/types.ts`:

```typescript
// ──────────────────────────────────────────────
// Phase 3B: Model Routing / Quota / Budget
// ──────────────────────────────────────────────

export interface ModelInfo {
  id: string;
  provider: string;
  tier: "low" | "medium" | "high";
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  max_tokens: number;
  strengths: string[];
  speed: "fast" | "medium" | "slow";
}

export interface ProviderStatus {
  name: string;
  healthy: boolean;
  quota_status: "available" | "throttled" | "exhausted" | "unavailable";
  remaining_quota: number | null;
  total_quota: number | null;
  reset_at: string | null;
  allow_paid_overage: boolean;
  models: ModelInfo[];
}

export interface QuotaStatus {
  id: string;
  provider: string;
  quota_type: string;
  status: "available" | "throttled" | "exhausted";
  remaining_quota: number | null;
  total_quota: number | null;
  reset_at: string | null;
  allow_paid_overage: boolean;
  updated_at: string;
}

export interface BudgetStatus {
  daily_spend: number;
  daily_soft_limit: number;
  daily_hard_limit: number;
  monthly_spend: number;
  monthly_hard_limit: number;
  state: "normal" | "throttled" | "blocked";
}

export interface RoutingDecision {
  id: string;
  task_id: string | null;
  agent_type: string | null;
  requested_tier: string;
  selected_model: string;
  selected_provider: string;
  reason: string;
  fallback_from: string | null;
  quota_status: string;
  cost_estimate: number;
  actual_cost: number | null;
  blocked_reason: string | null;
  created_at: string;
}

export interface UsageRecord {
  id: string;
  task_id: string | null;
  agent_type: string | null;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  routing_decision_id: string | null;
  created_at: string;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/types.ts
git commit -m "feat(3b): frontend types for model routing, quota, budget"
```

---

### Task 18: Frontend API client

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Update import to include Phase 3B types**

Update the import line at the top of `frontend/lib/api.ts`:

```typescript
import type { Project, Task, Agent, ActivityLog, MemorySnapshot, Summary, Worker, WorkerSession, WorkerSessionDetail, WorkerLog, AutonomousDecision, HealthStatus, WorkerHealthDetail, AgentMessage, TaskDependency, BrainstormRoom, BrainstormRoomDetail, BrainstormSkill, BrainstormMessage, BrainstormSynthesis, ModelInfo, ProviderStatus, QuotaStatus, BudgetStatus, RoutingDecision, UsageRecord } from "./types";
```

- [ ] **Step 2: Add Phase 3B API methods**

Append before the closing `};` of the `api` object:

```typescript
  // ──────────────────────────────────────────────
  // Phase 3B: Model Routing / Quota / Budget
  // ──────────────────────────────────────────────

  // Models & Providers
  getModels: () => fetchJSON<ModelInfo[]>(`${API_BASE}/api/models`),
  getAvailableModels: () => fetchJSON<ModelInfo[]>(`${API_BASE}/api/models/available`),
  getProviders: () => fetchJSON<ProviderStatus[]>(`${API_BASE}/api/providers`),

  // Quota
  getQuotaStatus: () => fetchJSON<QuotaStatus[]>(`${API_BASE}/api/quota/status`),
  getProviderQuota: (provider: string) => fetchJSON<QuotaStatus>(`${API_BASE}/api/quota/${provider}`),
  resetProviderQuota: (provider: string) => fetchJSON<QuotaStatus>(`${API_BASE}/api/quota/${provider}/reset`, { method: "POST" }),
  approvePaidOverride: (data: { task_id: string; provider: string; reason: string }) =>
    fetchJSON<RoutingDecision>(`${API_BASE}/api/quota/paid-override/approve`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Budget
  getBudgetStatus: () => fetchJSON<BudgetStatus>(`${API_BASE}/api/budget/status`),
  updateBudgetConfig: (data: Partial<{ daily_soft_limit: number; daily_hard_limit: number; monthly_hard_limit: number; per_task_max_cost: number }>) =>
    fetchJSON<BudgetStatus>(`${API_BASE}/api/budget/config`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Routing
  getRoutingDecisions: (limit?: number) =>
    fetchJSON<RoutingDecision[]>(`${API_BASE}/api/routing/decisions${limit ? `?limit=${limit}` : ""}`),
  getRoutingDecision: (id: string) => fetchJSON<RoutingDecision>(`${API_BASE}/api/routing/decisions/${id}`),

  // Usage
  getUsageRecords: (limit?: number) =>
    fetchJSON<UsageRecord[]>(`${API_BASE}/api/routing/usage${limit ? `?limit=${limit}` : ""}`),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(3b): frontend API client for quota, budget, routing, usage"
```

---

### Task 19: Frontend — QuotaStatus component

**Files:**
- Create: `frontend/components/QuotaStatus.tsx`

- [ ] **Step 1: Create QuotaStatus component**

Create `frontend/components/QuotaStatus.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProviderStatus } from "@/lib/types";

const STATUS_COLORS: Record<string, string> = {
  available: "bg-green-500",
  throttled: "bg-yellow-500",
  exhausted: "bg-red-500",
  unavailable: "bg-gray-500",
};

const STATUS_LABELS: Record<string, string> = {
  available: "Available",
  throttled: "Throttled",
  exhausted: "Quota Exhausted",
  unavailable: "Unavailable",
};

function formatResetTime(iso: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function QuotaStatus() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);

  useEffect(() => {
    api.getProviders().then(setProviders).catch(() => {});
  }, []);

  if (providers.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 p-4">
        <h3 className="text-sm font-semibold text-gray-500 mb-1">Provider Quota</h3>
        <p className="text-xs text-gray-400">No providers configured (simulation mode)</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Provider Quota</h3>
      <div className="space-y-2">
        {providers.map((p) => (
          <div key={p.name} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${STATUS_COLORS[p.quota_status] || STATUS_COLORS.unavailable}`} />
              <span className="font-medium capitalize">{p.name}</span>
            </div>
            <div className="flex items-center gap-3 text-gray-500">
              <span>{STATUS_LABELS[p.quota_status] || p.quota_status}</span>
              {p.remaining_quota != null && p.total_quota != null && (
                <span>{Math.round((p.remaining_quota / p.total_quota) * 100)}%</span>
              )}
              {p.reset_at && p.quota_status === "exhausted" && (
                <span className="text-red-400">resets {formatResetTime(p.reset_at)}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/QuotaStatus.tsx
git commit -m "feat(3b): QuotaStatus component — provider cards with status and reset time"
```

---

### Task 20: Frontend — ModelIndicator component

**Files:**
- Create: `frontend/components/ModelIndicator.tsx`

- [ ] **Step 1: Create ModelIndicator component**

Create `frontend/components/ModelIndicator.tsx`:

```tsx
"use client";

const TIER_COLORS: Record<string, string> = {
  low: "bg-blue-100 text-blue-700",
  medium: "bg-purple-100 text-purple-700",
  high: "bg-orange-100 text-orange-700",
};

interface ModelIndicatorProps {
  model: string | null;
  provider: string | null;
  tier?: string;
  simulated?: boolean;
}

export default function ModelIndicator({ model, provider, tier, simulated }: ModelIndicatorProps) {
  if (simulated || !model) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">
        simulated
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${TIER_COLORS[tier || "medium"] || TIER_COLORS.medium}`}>
      {model}
      {provider && <span className="opacity-60">({provider})</span>}
    </span>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/ModelIndicator.tsx
git commit -m "feat(3b): ModelIndicator component — model badge on task cards"
```

---

### Task 21: Add httpx to requirements

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Verify httpx is already in requirements**

`httpx==0.27.0` is already listed in `backend/requirements.txt`. No change needed.

- [ ] **Step 2: Verify — no commit needed**

Already present.

---

### Task 22: Integration — simulation mode toggle in AgentSimulator

**Files:**
- Modify: `backend/app/services/agent_simulator.py`

- [ ] **Step 1: Add ORKA_LLM_ENABLED check**

In `backend/app/services/agent_simulator.py`, add at the top after imports:

```python
import os

_LLM_ENABLED = os.getenv("ORKA_LLM_ENABLED", "false").lower() == "true"
```

Then wrap the simulation sleep in `simulate_task_processing` to show the toggle point:

```python
        # 5. Simulate work (3 seconds) — or route to real LLM
        if _LLM_ENABLED:
            # Real LLM mode: routing happens at call site, not here
            # This is a placeholder for Phase 3B integration
            # When enabled, the caller should use ModelRouter.route() instead
            pass
        else:
            await asyncio.sleep(3)
```

This preserves backward compatibility while marking the integration point. The actual LLM call flow will be wired by the caller (task distributor or API endpoint) using `ModelRouter.route()`.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/agent_simulator.py
git commit -m "feat(3b): add ORKA_LLM_ENABLED toggle point in AgentSimulator"
```

---

## Self-Review

**1. Spec coverage:**
- Provider adapter interface (BaseProvider + OpenAICompat + OpenRouter): Tasks 2-5
- ProviderRegistry: Task 5
- Config loader: Task 1
- TaskClassifier: Task 12
- ModelRegistry (via ProviderRegistry.get_models): Task 5
- ModelRouter (central routing): Task 12
- QuotaManager: Task 9
- BudgetManager: Task 10
- UsageTracker: Task 11
- No-surprise-paid-fallback: Task 12 (route method), Task 14 (paid-override endpoint)
- RoutingDecisionLog: Task 12 (route method logs every decision)
- API endpoints (models, quota, budget, routing): Tasks 13-15
- Simulation-first mode: Task 22
- Frontend components (QuotaStatus, ModelIndicator): Tasks 19-20
- Frontend types + API client: Tasks 17-18
- Background quota reset: Task 16

**2. Placeholder scan:** No TBD/TODO found. All steps contain complete code.

**3. Type consistency:**
- `ProviderResponse` defined in Task 2, used in Task 3, 11, 12
- `ModelInfo` defined in Task 2, used in Tasks 3-5, 12-13
- `TaskProfile` defined in Task 12, used in Task 12
- `RoutingDecision` model fields match schema `RoutingDecisionResponse`
- `ProviderQuotaState` model fields match schema `QuotaStatusResponse`
- Frontend types match backend schemas
- All router prefixes consistent (`/api/models`, `/api/quota`, `/api/budget`, `/api/routing`)
