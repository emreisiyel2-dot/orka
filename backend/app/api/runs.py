from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Run, RunEvent
from app.schemas import RunResponse, RunDetailResponse, RunEventResponse, AgentPerformanceResponse
from app.services.run_manager import RunManager

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/projects/{project_id}/runs", response_model=list[RunResponse])
async def list_project_runs(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Run)
        .where(Run.project_id == project_id)
        .order_by(Run.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/goals/{goal_id}/runs", response_model=list[RunResponse])
async def list_goal_runs(goal_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Run)
        .where(Run.goal_id == goal_id)
        .order_by(Run.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/tasks/{task_id}/runs", response_model=list[RunResponse])
async def list_task_runs(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Run)
        .where(Run.task_id == task_id)
        .order_by(Run.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/events", response_model=list[RunEventResponse])
async def get_run_events(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RunEvent)
        .where(RunEvent.run_id == run_id)
        .order_by(RunEvent.created_at)
    )
    return list(result.scalars().all())


@router.get("/runs/{run_id}/performance", response_model=list[AgentPerformanceResponse])
async def get_run_performance(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    mgr = RunManager()
    return await mgr.get_agent_performance(run.project_id, run.agent_type, db)
