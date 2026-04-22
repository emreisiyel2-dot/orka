from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task, Agent, ActivityLog
from app.schemas import TaskCreate, TaskResponse, TaskAssign
from app.services.task_distributor import TaskDistributor
from app.services.agent_simulator import AgentSimulator

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=List[TaskResponse])
async def list_tasks(
    project_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Task).order_by(Task.created_at.desc())
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    return tasks


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db)):
    task = Task(
        project_id=data.project_id,
        content=data.content,
        parent_task_id=data.parent_task_id,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: str, data: TaskAssign, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalars().first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(select(Agent).where(Agent.id == data.agent_id))
    agent = result.scalars().first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    task.assigned_agent_id = agent.id
    task.status = "assigned"
    agent.current_task_id = task.id

    log = ActivityLog(
        project_id=task.project_id,
        agent_id=agent.id,
        action="task_assigned",
        details=f"Task '{task.content}' assigned to {agent.name}",
    )
    db.add(log)
    await db.flush()
    await db.refresh(task)
    return task


@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalars().first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "completed"

    if task.assigned_agent_id:
        result = await db.execute(
            select(Agent).where(Agent.id == task.assigned_agent_id)
        )
        agent = result.scalars().first()
        if agent:
            agent.status = "idle"
            agent.current_task_id = None

    log = ActivityLog(
        project_id=task.project_id,
        agent_id=task.assigned_agent_id,
        action="task_completed",
        details=f"Task '{task.content}' marked as completed",
    )
    db.add(log)
    await db.flush()
    await db.refresh(task)
    return task


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalars().first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("failed", "completed"):
        raise HTTPException(status_code=400, detail="Can only retry failed or completed tasks")

    task.status = "pending"
    task.assigned_agent_id = None
    task.retry_count = (task.retry_count or 0) + 1

    log = ActivityLog(
        project_id=task.project_id,
        action="task_retried",
        details=f"Task '{task.content}' queued for retry (attempt {task.retry_count})",
    )
    db.add(log)
    await db.flush()
    await db.refresh(task)
    return task


@router.post("/{task_id}/distribute", response_model=TaskResponse)
async def distribute_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalars().first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    distributor = TaskDistributor()
    await distributor.distribute_task(task.id, db)

    await db.flush()
    result = await db.execute(select(Task).where(Task.id == task_id))
    return result.scalars().first()
