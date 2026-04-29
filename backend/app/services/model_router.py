import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_config import ModelRoutingConfig
from app.models import RoutingDecision
from app.providers.base import BaseProvider, ModelInfo, ProviderResponse
from app.providers.registry import ProviderRegistry
from app.services.budget_manager import BudgetManager
from app.services.cli_quota_tracker import CLIQuotaTracker
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
    execution_mode: str = "auto"


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

_CLI_PREFERRED_TASK_TYPES = {"code_gen", "review", "planning"}
_API_PREFERRED_TASK_TYPES = {"docs", "analysis"}

_CLI_ROUTING_POLICY: dict[tuple[str, str], list[str]] = {
    ("code_gen", "complex"): ["claude_code", "glm_coding"],
    ("review", "complex"):   ["claude_code", "glm_coding"],
    ("planning", "complex"): ["claude_code", "glm_coding"],
    ("code_gen", "simple"):  ["glm_coding", "claude_code"],
    ("code_gen", "medium"):  ["glm_coding", "claude_code"],
    ("review", "simple"):    ["glm_coding", "claude_code"],
    ("review", "medium"):    ["claude_code", "glm_coding"],
    ("analysis", "simple"):  ["glm_coding", "claude_code"],
    ("analysis", "medium"):  ["claude_code", "glm_coding"],
    ("analysis", "complex"): ["claude_code"],
    ("docs", "simple"):      ["glm_coding", "claude_code"],
    ("docs", "medium"):      ["glm_coding", "claude_code"],
    ("docs", "complex"):     ["claude_code", "glm_coding"],
    ("planning", "simple"):  ["glm_coding", "claude_code"],
    ("planning", "medium"):  ["claude_code", "glm_coding"],
}

_CLI_DEFAULT_ORDER = ["claude_code", "glm_coding"]


def lookup_cli_policy(task_type: str, complexity: str) -> list[str]:
    return _CLI_ROUTING_POLICY.get(
        (task_type, complexity), _CLI_DEFAULT_ORDER,
    )


def classify_task(
    content: str,
    agent_type: str,
    importance: str = "normal",
    has_cli_providers: bool = False,
) -> TaskProfile:
    budget_tier = _AGENT_TIER_DEFAULTS.get(agent_type, "medium")
    lower = content.lower()

    complexity = "medium"
    for level, keywords in _COMPLEXITY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            complexity = level
            break

    if len(content) < 100 and complexity == "medium":
        complexity = "simple"

    task_type = "code_gen"
    if any(w in lower for w in ["doc", "readme", "comment", "explain"]):
        task_type = "docs"
    elif any(w in lower for w in ["test", "qa", "review", "check"]):
        task_type = "review"
    elif any(w in lower for w in ["analyz", "investigat", "assess"]):
        task_type = "analysis"
    elif any(w in lower for w in ["plan", "design", "architect"]):
        task_type = "planning"

    context_size = len(content.split()) * 2

    if importance == "critical":
        budget_tier = "high"

    # Determine execution mode
    execution_mode = "api"
    if task_type in _CLI_PREFERRED_TASK_TYPES and has_cli_providers:
        execution_mode = "cli"
    elif task_type in _API_PREFERRED_TASK_TYPES:
        execution_mode = "api"
    elif has_cli_providers:
        execution_mode = "cli"

    return TaskProfile(
        complexity=complexity,
        importance=importance,
        task_type=task_type,
        context_size=context_size,
        agent_type=agent_type,
        budget_tier=budget_tier,
        execution_mode=execution_mode,
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
        self._cli_quota = CLIQuotaTracker(
            max_concurrent=max(p.max_concurrent for p in config.cli_providers) if config.cli_providers else 3,
            max_sessions_per_hour=max(p.max_sessions_per_hour for p in config.cli_providers) if config.cli_providers else 20,
        )

    def _select_model_by_complexity(self, models: list, complexity: str) -> str:
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

    def _reorder_by_adaptive_signals(
        self, provider_order: list[str], task_type: str, complexity: str,
    ) -> list[str]:
        """Reorder providers using explicit adaptive thresholds.

        Thresholds:
          - failure_rate > 0.5 with >=3 runs  -> +30 (deprioritize)
          - failure_rate > 0.2 with >=3 runs  -> +15 (deprioritize)
          - success_rate > 0.8 with >=5 runs  -> -10 (boost)
          - status == "blocked"               -> +50 (skip)
          - status == "throttled"             -> +20 (deprioritize)
          - no data                           -> base score only (use static order)
        """
        scored = []
        for i, name in enumerate(provider_order):
            usage = self._cli_quota.get_usage(name)
            signals = self._cli_quota.get_adaptive_signals(name)

            base_score = i * 10

            total = signals.get("total_sessions", 0)
            failure_rate = signals.get("recent_failure_rate", 0.0)
            success_rate = signals.get("recent_success_rate", 1.0)

            failure_penalty = 0
            if total >= 3:
                if failure_rate > 0.5:
                    failure_penalty = 30
                elif failure_rate > 0.2:
                    failure_penalty = 15

            success_boost = 0
            if total >= 5 and success_rate > 0.8:
                success_boost = 10

            status_penalty = 0
            if usage and usage.status == "blocked":
                status_penalty = 50
            elif usage and usage.status == "throttled":
                status_penalty = 20

            scored.append((name, base_score + failure_penalty - success_boost + status_penalty))

        scored.sort(key=lambda x: x[1])
        return [name for name, _ in scored]

    async def decide(
        self, prompt: str, profile: TaskProfile, task_id: str | None, db: AsyncSession,
    ) -> RoutingDecision:
        """Pure decision engine -- evaluate providers and return routing decision.

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

    async def _decide_api(
        self, prompt: str, profile: TaskProfile, task_id: str | None,
        db: AsyncSession, execution_mode: str,
    ) -> RoutingDecision:
        """Decide which API provider to use. No execution."""
        target_model = _tier_to_model(profile.budget_tier, self._config)
        provider, model_info, quota_status = await self._find_available_provider(
            target_model, profile, db,
        )
        if provider is None and profile.budget_tier != "low":
            lower_tier = "medium" if profile.budget_tier in ("high", "dynamic") else "low"
            target_model = _tier_to_model(lower_tier, self._config)
            provider, model_info, quota_status = await self._find_available_provider(
                target_model, profile, db,
            )

        if provider is None:
            decision = RoutingDecision(
                task_id=task_id,
                agent_type=profile.agent_type,
                requested_tier=profile.budget_tier,
                selected_model="none",
                selected_provider="none",
                reason="all_api_unavailable",
                quota_status="exhausted",
                cost_estimate=0.0,
                execution_mode=execution_mode,
                task_complexity=profile.complexity,
                considered_providers=json.dumps(["api"]),
                rejected_providers=json.dumps([{"provider": "api", "reason": "quota_exhausted"}]),
            )
            decision.blocked_reason = "no_api_provider_available"
            db.add(decision)
            await db.flush()
            return decision

        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model=target_model,
            selected_provider=provider.name,
            reason="api_auto",
            quota_status=quota_status,
            cost_estimate=provider.estimate_cost(profile.context_size, target_model),
            execution_mode=execution_mode,
            task_complexity=profile.complexity,
            considered_providers=json.dumps([provider.name]),
        )
        db.add(decision)
        await db.flush()
        return decision

    async def route(
        self, prompt: str, profile: TaskProfile, task_id: str | None, db: AsyncSession,
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Pure forwarding wrapper -- calls decide() and delegates execution.

        Contains NO routing logic, NO fallback chains, NO retry logic.
        All routing intelligence lives in decide().
        """
        available_providers = self._registry.all()
        if available_providers:
            for pname, prov in available_providers.items():
                models = [m.id for m in prov.get_models()]
                print(f"[ModelRouter] provider='{pname}' models={models}")
        else:
            print(f"[ModelRouter] WARNING: no providers configured")

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

    async def _execute_cli(
        self, decision: RoutingDecision, prompt: str, profile: TaskProfile,
        task_id: str | None, db: AsyncSession,
    ) -> ProviderResponse | None:
        """Execute a CLI routing decision. Returns response or None."""
        from app.models import WorkerSession

        provider_name = decision.selected_provider
        if provider_name == "none":
            return None

        cli_providers = self._registry.all_by_mode()["cli"]
        provider = next((p for p in cli_providers if p.name == provider_name), None)
        if provider is None:
            return None

        session = None
        if task_id is not None:
            session = WorkerSession(
                worker_id=f"cli-{provider.name}",
                task_id=task_id,
                status="running",
            )
            db.add(session)
            await db.flush()

        self._cli_quota.start_session(provider.name)
        response = None
        try:
            response = await provider.complete(prompt=prompt, model=decision.selected_model)
            if session:
                session.status = "completed"
                session.exit_code = 0
        except Exception as exc:
            if session:
                session.status = "error"
                session.exit_code = 1
            print(f"[ModelRouter] CLI provider '{provider.name}' error: {exc}")
        finally:
            if session:
                session.updated_at = datetime.now(timezone.utc)
            self._cli_quota.end_session(provider.name)
            try:
                await db.flush()
            except Exception:
                pass

        if response is None:
            return None

        self._cli_quota.record_session(provider.name, duration_seconds=response.latency_ms / 1000.0)
        return response

    def _resolve_execution_mode(self, profile: TaskProfile) -> str:
        """Resolve 'auto' execution mode to a concrete mode."""
        if profile.execution_mode != "auto":
            return profile.execution_mode

        has_cli = self._registry.has_cli_providers()
        has_api = len(self._registry.all_by_mode()["api"]) > 0

        if profile.task_type in _CLI_PREFERRED_TASK_TYPES and has_cli:
            return "cli"
        if profile.task_type in _API_PREFERRED_TASK_TYPES and has_api:
            return "api"
        if has_cli:
            return "cli"
        if has_api:
            return "api"
        return "simulated"

    async def _try_api_route(
        self, prompt: str, profile: TaskProfile, task_id: str | None,
        db: AsyncSession, execution_mode: str,
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Try to route via an API provider."""
        target_model = _tier_to_model(profile.budget_tier, self._config)

        provider, model_info, quota_status = await self._find_available_provider(
            target_model, profile, db
        )

        fallback_from = None
        if provider is None and profile.budget_tier != "low":
            fallback_from = target_model
            lower_tier = "medium" if profile.budget_tier in ("high", "dynamic") else "low"
            target_model = _tier_to_model(lower_tier, self._config)
            provider, model_info, quota_status = await self._find_available_provider(
                target_model, profile, db
            )

        if provider is None:
            return None, None

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
                execution_mode="api",
            )
            db.add(decision)
            await db.flush()
            return None, decision

        reason = "auto"
        if fallback_from:
            reason = "fallback_quota_exhausted"
        elif quota_status == "throttled":
            reason = "quota_throttle"
        elif budget_state == "throttled":
            reason = "budget_throttle"

        try:
            response = await provider.complete(prompt=prompt, model=target_model)
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
                execution_mode="api",
            )
            db.add(decision)
            await db.flush()
            return None, decision

        reason_str = "api_fallback" if execution_mode == "cli" else reason
        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model=target_model,
            selected_provider=provider.name,
            reason=reason_str,
            fallback_from=fallback_from,
            quota_status=quota_status,
            cost_estimate=estimated_cost,
            actual_cost=response.cost_usd,
            execution_mode="api",
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
