from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Run
from app.schemas import RunFeedbackResponse, RetryEvaluationResponse
from app.services.feedback_service import FeedbackService
from app.services.retry_intelligence import RetryIntelligence

router = APIRouter(prefix="/api", tags=["learning"])


class AnalyzeRequest(BaseModel):
    project_id: str


@router.post("/feedback/run/{run_id}", response_model=RunFeedbackResponse)
async def reprocess_feedback(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    feedback = FeedbackService().process_run(run)
    run.feedback_score = feedback.quality_score
    run.failure_classification = feedback.failure_classification
    await db.flush()
    return RunFeedbackResponse(
        run_id=feedback.run_id,
        success=feedback.success,
        quality_score=feedback.quality_score,
        failure_classification=feedback.failure_classification,
    )


@router.post("/retry/evaluate/{run_id}", response_model=RetryEvaluationResponse)
async def re_evaluate_retry(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    retry = RetryIntelligence().evaluate(run)
    run.retry_eligible = retry.eligible
    run.retry_reason = retry.reason
    await db.flush()
    return RetryEvaluationResponse(
        eligible=retry.eligible,
        reason=retry.reason,
        strategy=retry.strategy,
        max_retries=retry.max_retries,
    )


@router.post("/learning/analyze")
async def trigger_learning_analysis(
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.rd_manager import RDManager

    rd = RDManager()
    proposals = await rd.submit_to_research(
        project_id=body.project_id, db=db,
    )
    return {
        "project_id": body.project_id,
        "proposals_created": len(proposals),
        "proposal_ids": [p.id for p in proposals],
    }
