from fastapi import APIRouter, Depends, HTTPException, Query
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
