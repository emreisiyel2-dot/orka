from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Goal
from app.schemas import GoalCreate, GoalResponse, GoalUpdate, GoalProgressResponse
from app.services.run_manager import RunManager

router = APIRouter(prefix="/api", tags=["goals"])


@router.get("/projects/{project_id}/goals", response_model=list[GoalResponse])
async def list_goals(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Goal)
        .where(Goal.project_id == project_id)
        .order_by(Goal.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/projects/{project_id}/goals", response_model=GoalResponse, status_code=201)
async def create_goal(
    project_id: str, data: GoalCreate, db: AsyncSession = Depends(get_db)
):
    goal = Goal(
        project_id=project_id,
        title=data.title,
        description=data.description,
        source=data.source,
        type=data.type,
        target_description=data.target_description,
        status="planned",
    )
    db.add(goal)
    await db.flush()
    return goal


@router.get("/goals/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Goal).where(Goal.id == goal_id))
    goal = result.scalars().first()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@router.patch("/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: str, data: GoalUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Goal).where(Goal.id == goal_id))
    goal = result.scalars().first()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")

    if data.status is not None:
        goal.status = data.status
        if data.status == "completed":
            goal.completed_at = datetime.now(timezone.utc)
    if data.title is not None:
        goal.title = data.title
    if data.description is not None:
        goal.description = data.description

    goal.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return goal


@router.get("/goals/{goal_id}/progress", response_model=GoalProgressResponse)
async def get_goal_progress(goal_id: str, db: AsyncSession = Depends(get_db)):
    mgr = RunManager()
    progress = await mgr.get_goal_progress(goal_id, db)
    if progress is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return progress
