from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ImprovementProposal
from app.schemas import (
    AnalysisRequest,
    ProposalReview,
    GuardConfirm,
    ImprovementProposalResponse,
    ApprovalGuardResponse,
    ProposalConversionResponse,
    GoalResponse,
)
from app.services.rd_manager import RDManager

router = APIRouter(prefix="/api", tags=["research"])


# ── Analysis ──


@router.post("/projects/{project_id}/research/analyze", response_model=list[ImprovementProposalResponse])
async def analyze_project(
    project_id: str, data: AnalysisRequest, db: AsyncSession = Depends(get_db),
):
    mgr = RDManager()
    proposals = await mgr.submit_to_research(
        project_id=project_id,
        goal_id=data.goal_id,
        analysis_types=data.analysis_types,
        db=db,
    )
    return proposals


@router.post("/goals/{goal_id}/research/analyze", response_model=list[ImprovementProposalResponse])
async def analyze_goal(goal_id: str, db: AsyncSession = Depends(get_db)):
    from app.services.proposal_generator import ProposalGenerator

    generator = ProposalGenerator()
    proposals = await generator.generate_from_goal(goal_id, db)
    return proposals


# ── Proposal management ──


@router.get("/projects/{project_id}/proposals", response_model=list[ImprovementProposalResponse])
async def list_proposals(
    project_id: str, status: str | None = None, db: AsyncSession = Depends(get_db),
):
    mgr = RDManager()
    return await mgr.get_project_proposals(project_id, status=status, db=db)


@router.get("/projects/{project_id}/proposals/summary")
async def proposals_summary(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ImprovementProposal.status, func.count(ImprovementProposal.id))
        .where(ImprovementProposal.project_id == project_id)
        .group_by(ImprovementProposal.status)
    )
    counts = {row[0]: row[1] for row in result.all()}

    result = await db.execute(
        select(ImprovementProposal).where(
            ImprovementProposal.project_id == project_id,
            ImprovementProposal.status.in_(["draft", "under_review"]),
        ).order_by(ImprovementProposal.created_at.desc()).limit(5)
    )
    recent = result.scalars().all()

    return {
        "project_id": project_id,
        "counts": counts,
        "total": sum(counts.values()),
        "recent_proposals": [
            {"id": p.id, "title": p.title, "status": p.status, "risk_level": p.risk_level}
            for p in recent
        ],
    }


@router.get("/proposals/{proposal_id}", response_model=ImprovementProposalResponse)
async def get_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ImprovementProposal).where(ImprovementProposal.id == proposal_id)
    )
    proposal = result.scalars().first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.patch("/proposals/{proposal_id}/submit", response_model=ImprovementProposalResponse)
async def submit_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    mgr = RDManager()
    try:
        return await mgr.submit_for_review(proposal_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/proposals/{proposal_id}/guard", response_model=ApprovalGuardResponse)
async def get_proposal_guard(proposal_id: str, db: AsyncSession = Depends(get_db)):
    mgr = RDManager()
    try:
        return await mgr.run_approval_guard(proposal_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/proposals/{proposal_id}/approve", response_model=ImprovementProposalResponse)
async def approve_proposal(
    proposal_id: str, data: GuardConfirm, db: AsyncSession = Depends(get_db),
):
    mgr = RDManager()
    try:
        return await mgr.approve_proposal(
            proposal_id,
            reviewer=data.reviewer,
            notes=data.notes,
            guard_confirmed=data.guard_confirmed,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/proposals/{proposal_id}/convert", response_model=ProposalConversionResponse)
async def convert_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    mgr = RDManager()
    try:
        proposal, goal = await mgr.convert_to_goal(proposal_id, db)
        # Count tasks created under the goal
        from app.models import Task
        result = await db.execute(
            select(func.count()).select_from(Task).where(Task.goal_id == goal.id)
        )
        tasks_count = result.scalar() or 0
        return ProposalConversionResponse(
            proposal=ImprovementProposalResponse.model_validate(proposal),
            implementation_goal=GoalResponse.model_validate(goal),
            tasks_created=tasks_count,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/proposals/{proposal_id}/reject", response_model=ImprovementProposalResponse)
async def reject_proposal(
    proposal_id: str, data: ProposalReview, db: AsyncSession = Depends(get_db),
):
    mgr = RDManager()
    try:
        return await mgr.reject_proposal(
            proposal_id, reviewer=data.reviewer, reason=data.notes, db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/proposals/{proposal_id}/archive", response_model=ImprovementProposalResponse)
async def archive_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    mgr = RDManager()
    try:
        return await mgr.archive_proposal(proposal_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
