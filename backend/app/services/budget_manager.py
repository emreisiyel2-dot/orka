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
