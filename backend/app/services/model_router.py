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
        prompt: str,
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

        # 5. Determine reason string
        reason = "auto"
        if fallback_from:
            reason = "fallback_quota_exhausted"
        elif quota_status == "throttled":
            reason = "quota_throttle"
        elif budget_state == "throttled":
            reason = "budget_throttle"

        # 6. Execute the call
        try:
            response = await provider.complete(
                prompt=prompt,
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

        # 7. Record decision + usage
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
