from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_config import ModelRoutingConfig
from app.models import ProviderQuotaState


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
