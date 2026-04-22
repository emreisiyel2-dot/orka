from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, Task, Agent, ActivityLog, MemorySnapshot
from app.schemas import (
    SummaryResponse,
    AgentSummary,
    ActivityLogResponse,
    MemorySnapshotResponse,
)

router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("/{project_id}", response_model=SummaryResponse)
async def get_summary(project_id: str, db: AsyncSession = Depends(get_db)):
    # Fetch project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Count tasks by status
    result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.project_id == project_id)
        .group_by(Task.status)
    )
    status_counts = dict(result.all())

    total_tasks = sum(status_counts.values())
    completed_tasks = status_counts.get("completed", 0)
    in_progress_tasks = status_counts.get("in_progress", 0)
    pending_tasks = status_counts.get("pending", 0)

    # Fetch agents
    result = await db.execute(select(Agent).order_by(Agent.created_at))
    agents = result.scalars().all()
    agent_summaries = [
        AgentSummary(name=a.name, type=a.type, status=a.status) for a in agents
    ]

    # Fetch recent activity (last 10)
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.project_id == project_id)
        .order_by(ActivityLog.timestamp.desc())
        .limit(10)
    )
    recent_logs = result.scalars().all()
    recent_activity = [ActivityLogResponse.model_validate(log) for log in recent_logs]

    # Fetch memory snapshot
    result = await db.execute(
        select(MemorySnapshot)
        .where(MemorySnapshot.project_id == project_id)
        .order_by(MemorySnapshot.updated_at.desc())
        .limit(1)
    )
    memory_row = result.scalars().first()
    memory = MemorySnapshotResponse.model_validate(memory_row) if memory_row else None

    # Determine overall status
    working_agents = [a for a in agents if a.status == "working"]
    error_agents = [a for a in agents if a.status == "error"]
    idle_agents = [a for a in agents if a.status == "idle"]

    if error_agents:
        overall_status = "blocked"
    elif working_agents:
        overall_status = "healthy"
    else:
        overall_status = "idle"

    # Build human-readable message
    parts = []
    if total_tasks == 0:
        parts.append(f"Project '{project.name}' has no tasks yet.")
    else:
        parts.append(
            f"Project '{project.name}' has {total_tasks} tasks: "
            f"{completed_tasks} completed, {in_progress_tasks} in progress, "
            f"and {pending_tasks} pending."
        )

    if working_agents:
        names = ", ".join(a.name for a in working_agents)
        parts.append(f"Currently working: {names}.")
    elif error_agents:
        names = ", ".join(a.name for a in error_agents)
        parts.append(f"Blocked by errors on: {names}.")
    else:
        parts.append("All agents are currently idle.")

    if memory and memory.next_step:
        parts.append(f"Next step: {memory.next_step}")

    message = " ".join(parts)

    return SummaryResponse(
        project_name=project.name,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        in_progress_tasks=in_progress_tasks,
        pending_tasks=pending_tasks,
        agents=agent_summaries,
        recent_activity=recent_activity,
        memory=memory,
        overall_status=overall_status,
        message=message,
    )
