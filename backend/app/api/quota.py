from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config.model_config import load_config
from app.models import RoutingDecision
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
