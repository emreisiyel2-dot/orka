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

    async def route(
        self,
        prompt: str,
        profile: TaskProfile,
        task_id: str | None,
        db: AsyncSession,
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Route a task to the best available model. Returns (response, decision)."""
        available_providers = self._registry.all()
        if available_providers:
            for pname, prov in available_providers.items():
                models = [m.id for m in prov.get_models()]
                print(f"[ModelRouter] provider='{pname}' models={models}")
        else:
            print(f"[ModelRouter] WARNING: no providers configured")

        execution_mode = self._resolve_execution_mode(profile)
        print(f"[ModelRouter] execution_mode={execution_mode} task_type={profile.task_type} tier={profile.budget_tier}")

        # Try CLI path if applicable
        if execution_mode == "cli":
            response, decision = await self._try_cli_route(
                prompt, profile, task_id, db
            )
            if response is not None:
                return response, decision
            print(f"[ModelRouter] CLI route failed/blocked, falling back to API")

        # Try API path
        response, decision = await self._try_api_route(
            prompt, profile, task_id, db, execution_mode
        )
        if response is not None:
            return response, decision

        # No provider available
        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model="none",
            selected_provider="none",
            reason="all_providers_exhausted",
            fallback_from=None,
            quota_status="exhausted",
            cost_estimate=0.0,
            blocked_reason="no_provider_with_quota",
            execution_mode=execution_mode,
        )
        db.add(decision)
        await db.flush()
        return None, decision

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

    async def _try_cli_route(
        self, prompt: str, profile: TaskProfile, task_id: str | None, db: AsyncSession
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Try to route via a CLI provider."""
        from app.models import WorkerSession

        cli_providers = self._registry.all_by_mode()["cli"]
        if not cli_providers:
            return None, None

        provider = None
        quota_status = "available"
        for cp in cli_providers:
            quota_status = self._cli_quota.check_available(cp.name)
            if quota_status != "blocked":
                healthy = await cp.health_check()
                if healthy:
                    provider = cp
                    break
                else:
                    cp.invalidate_cache()

        if provider is None:
            return None, None

        models = provider.get_models()
        target_model = models[0].id if models else "unknown"

        # Create WorkerSession for CLI execution tracking
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
            response = await provider.complete(prompt=prompt, model=target_model)
            session.status = "completed"
            session.exit_code = 0
        except Exception as exc:
            session.status = "error"
            session.exit_code = 1
            print(f"[ModelRouter] CLI provider '{provider.name}' error: {exc}")
        finally:
            # GUARANTEED: session always closed + quota always released
            session.updated_at = datetime.now(timezone.utc)
            self._cli_quota.end_session(provider.name)
            try:
                await db.flush()
            except Exception:
                pass

        if response is None:
            return None, None

        self._cli_quota.record_session(provider.name, duration_seconds=response.latency_ms / 1000.0)

        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model=target_model,
            selected_provider=provider.name,
            reason="cli_primary",
            fallback_from=None,
            quota_status=quota_status,
            cost_estimate=0.0,
            actual_cost=0.0,
            execution_mode="cli",
        )
        db.add(decision)
        await db.flush()

        return response, decision

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
