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
