"""Task dependency API — create, list, satisfy dependencies."""

from typing import List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TaskDependency, Task, ActivityLog
from app.schemas import TaskDependencyCreate, TaskDependencyResponse

router = APIRouter(prefix="/api/dependencies", tags=["dependencies"])


def _enrich(dep: TaskDependency) -> dict:
    return {
        "id": dep.id,
        "task_id": dep.task_id,
        "depends_on_task_id": dep.depends_on_task_id,
        "status": dep.status,
        "created_at": dep.created_at,
        "satisfied_at": dep.satisfied_at,
        "task_content": dep.task.content[:80] if dep.task else None,
        "depends_on_content": dep.depends_on_task.content[:80] if dep.depends_on_task else None,
    }


@router.post("", response_model=TaskDependencyResponse, status_code=201)
async def create_dependency(
    data: TaskDependencyCreate, db: AsyncSession = Depends(get_db)
):
    if data.task_id == data.depends_on_task_id:
        raise HTTPException(400, "Task cannot depend on itself")

    task = (await db.execute(select(Task).where(Task.id == data.task_id))).scalars().first()
    if task is None:
        raise HTTPException(404, "Task not found")
    dep_task = (await db.execute(select(Task).where(Task.id == data.depends_on_task_id))).scalars().first()
    if dep_task is None:
        raise HTTPException(404, "depends_on_task not found")

    dep = TaskDependency(task_id=data.task_id, depends_on_task_id=data.depends_on_task_id)
    db.add(dep)
    await db.flush()
    await db.refresh(dep)
    dep = (await db.execute(select(TaskDependency).where(TaskDependency.id == dep.id))).scalars().first()
    return _enrich(dep)


@router.get("/task/{task_id}", response_model=List[TaskDependencyResponse])
async def task_dependencies(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskDependency).where(TaskDependency.task_id == task_id)
    )
    return [_enrich(d) for d in result.scalars().all()]


@router.get("/blocked", response_model=List[TaskDependencyResponse])
async def blocked_dependencies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TaskDependency).where(TaskDependency.status == "pending")
    )
    return [_enrich(d) for d in result.scalars().all()]


@router.get("/project/{project_id}", response_model=List[TaskDependencyResponse])
async def project_dependencies(project_id: str, db: AsyncSession = Depends(get_db)):
    task_ids = select(Task.id).where(Task.project_id == project_id)
    result = await db.execute(
        select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
    )
    return [_enrich(d) for d in result.scalars().all()]


@router.post("/{dep_id}/satisfy", response_model=TaskDependencyResponse)
async def satisfy_dependency(dep_id: str, db: AsyncSession = Depends(get_db)):
    dep = (await db.execute(select(TaskDependency).where(TaskDependency.id == dep_id))).scalars().first()
    if dep is None:
        raise HTTPException(404, "Dependency not found")

    dep.status = "satisfied"
    dep.satisfied_at = datetime.now(timezone.utc)

    # Check if ALL deps for this task are now satisfied
    remaining = (await db.execute(
        select(TaskDependency).where(
            TaskDependency.task_id == dep.task_id,
            TaskDependency.status == "pending",
        )
    )).scalars().first()

    if remaining is None:
        # All deps satisfied — unblock the task
        task = (await db.execute(select(Task).where(Task.id == dep.task_id))).scalars().first()
        if task and task.status == "pending":
            task.status = "assigned"
            log = ActivityLog(
                project_id=task.project_id,
                action="task_unblocked",
                details=f"Task '{task.content}' unblocked — all dependencies satisfied",
            )
            db.add(log)

    await db.flush()
    dep = (await db.execute(select(TaskDependency).where(TaskDependency.id == dep_id))).scalars().first()
    return _enrich(dep)
