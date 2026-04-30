"""Phase 6B: Controlled Auto Execution API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ImprovementProposal, ActivityLog
from app.schemas import (
    AutoEligibleRequest,
    AutoExecuteResponse,
    AutoStatusResponse,
    ImprovementProposalResponse,
)
from app.services.auto_executor import AutoExecutor
from app.services.safety_engine import SafetyEngine

router = APIRouter(prefix="/api/auto", tags=["auto"])


@router.post("/proposals/{proposal_id}/eligible", response_model=ImprovementProposalResponse)
async def set_auto_eligible(
    proposal_id: str,
    body: AutoEligibleRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ImprovementProposal).where(ImprovementProposal.id == proposal_id)
    )
    proposal = result.scalars().first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != "approved":
        raise HTTPException(
            status_code=422,
            detail=f"Proposal must be approved (current: {proposal.status})",
        )

    if proposal.risk_level in ("high", "critical"):
        raise HTTPException(
            status_code=422,
            detail=f"High/critical risk proposals cannot be auto-executed (risk: {proposal.risk_level})",
        )

    proposal.auto_execution_eligible = body.eligible
    proposal.updated_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )
    await db.flush()

    return ImprovementProposalResponse.model_validate(proposal)


@router.post("/execute", response_model=AutoExecuteResponse)
async def execute_auto(
    dry_run: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    executor = AutoExecutor()
    result = await executor.execute(db, dry_run=dry_run)
    return AutoExecuteResponse(**result)


@router.get("/status", response_model=AutoStatusResponse)
async def auto_status(db: AsyncSession = Depends(get_db)):
    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )
    safety = SafetyEngine()

    # Eligible count
    result = await db.execute(
        select(func.count()).select_from(ImprovementProposal).where(
            ImprovementProposal.status == "approved",
            ImprovementProposal.auto_execution_eligible.is_(True),
            ImprovementProposal.auto_executed.is_(False),
        )
    )
    eligible_count = result.scalar() or 0

    # Last auto execution
    last_result = await db.execute(
        select(ActivityLog).where(
            ActivityLog.action == "auto_executed",
        ).order_by(ActivityLog.timestamp.desc()).limit(1)
    )
    last_log = last_result.scalars().first()
    last_auto_execution = last_log.created_at if last_log else None

    # Velocity remaining
    from datetime import timedelta
    cutoff = now - timedelta(hours=1)
    vel_result = await db.execute(
        select(func.count()).select_from(ActivityLog).where(
            ActivityLog.action == "auto_executed",
            ActivityLog.timestamp >= cutoff,
        )
    )
    vel_count = vel_result.scalar() or 0
    velocity_remaining = max(0, 1 - vel_count)

    # Failure rate
    recent_result = await db.execute(
        select(ActivityLog).where(
            ActivityLog.action.in_(["auto_executed", "auto_execution_failed"]),
        ).order_by(ActivityLog.timestamp.desc()).limit(10)
    )
    recent = list(recent_result.scalars().all())
    failure_rate = 0.0
    if recent:
        failures = sum(1 for e in recent if e.action == "auto_execution_failed")
        failure_rate = round(failures / len(recent), 2)

    # Gate states
    try:
        from app.services.budget_manager import BudgetManager
        bm = BudgetManager()
        budget_state = await bm.get_state(db)
    except Exception:
        budget_state = "unknown"

    gates = {
        "budget": budget_state,
        "velocity": "available" if velocity_remaining > 0 else "exhausted",
        "duplicate": "clear",
        "failure_rate": "acceptable" if failure_rate <= 0.5 else "elevated",
    }

    return AutoStatusResponse(
        eligible_count=eligible_count,
        last_auto_execution=last_auto_execution,
        velocity_remaining=velocity_remaining,
        recent_failure_rate=failure_rate,
        gates=gates,
    )
