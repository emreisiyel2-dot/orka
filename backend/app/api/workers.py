"""Worker-facing API endpoints — registration, task fetching, session management, log streaming."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Worker, WorkerSession, WorkerLog, AutonomousDecision, Task, Agent
from app.schemas import (
    WorkerRegister,
    WorkerResponse,
    WorkerSessionCreate,
    WorkerSessionUpdate,
    WorkerSessionResponse,
    WorkerLogCreate,
    WorkerLogResponse,
    AutonomousDecisionCreate,
    AutonomousDecisionResponse,
)

router = APIRouter(prefix="/api/workers", tags=["workers"])


# ── Worker Registration ──────────────────────


@router.post("/register", response_model=WorkerResponse, status_code=201)
async def register_worker(data: WorkerRegister, db: AsyncSession = Depends(get_db)):
    worker = Worker(name=data.name, hostname=data.hostname, platform=data.platform)
    db.add(worker)
    await db.flush()
    await db.refresh(worker)
    return worker


@router.get("", response_model=List[WorkerResponse])
async def list_workers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).order_by(Worker.created_at.desc()))
    return result.scalars().all()


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalars().first()
    if worker is None:
        raise HTTPException(404, "Worker not found")
    return worker


@router.put("/{worker_id}/heartbeat", response_model=WorkerResponse)
async def heartbeat(worker_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalars().first()
    if worker is None:
        raise HTTPException(404, "Worker not found")
    worker.status = "online"
    await db.flush()
    await db.refresh(worker)
    return worker


@router.get("/{worker_id}/health")
async def worker_health(worker_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalars().first()
    if worker is None:
        raise HTTPException(404, "Worker not found")

    active = await db.execute(
        select(func.count()).select_from(WorkerSession).where(
            WorkerSession.worker_id == worker_id,
            WorkerSession.status.in_(["running", "waiting_input"]),
        )
    )
    total = await db.execute(
        select(func.count()).select_from(WorkerSession).where(
            WorkerSession.worker_id == worker_id,
        )
    )
    return {
        "id": worker.id,
        "name": worker.name,
        "status": worker.status,
        "last_heartbeat": worker.last_heartbeat.isoformat(),
        "active_sessions": active.scalar(),
        "total_sessions": total.scalar(),
    }


# ── Task Fetching ────────────────────────────


@router.get("/{worker_id}/tasks", response_model=List[dict])
async def fetch_pending_tasks(
    worker_id: str,
    agent_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    if result.scalars().first() is None:
        raise HTTPException(404, "Worker not found")

    stmt = select(Task).where(Task.status == "assigned")
    if agent_type:
        agent_sub = select(Agent.id).where(Agent.type == agent_type)
        stmt = stmt.where(Task.assigned_agent_id.in_(agent_sub))

    result = await db.execute(stmt.order_by(Task.created_at))
    tasks = result.scalars().all()

    response = []
    for t in tasks:
        agent_name = None
        if t.assigned_agent_id:
            ag = await db.execute(select(Agent).where(Agent.id == t.assigned_agent_id))
            agent_obj = ag.scalars().first()
            if agent_obj:
                agent_name = agent_obj.name
        response.append(
            {
                "id": t.id,
                "project_id": t.project_id,
                "content": t.content,
                "assigned_agent_id": t.assigned_agent_id,
                "agent_name": agent_name,
            }
        )
    return response


# ── Session Management ───────────────────────


@router.post("/sessions", response_model=WorkerSessionResponse, status_code=201)
async def create_session(data: WorkerSessionCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.id == data.worker_id))
    if result.scalars().first() is None:
        raise HTTPException(404, "Worker not found")

    result = await db.execute(select(Task).where(Task.id == data.task_id))
    if result.scalars().first() is None:
        raise HTTPException(404, "Task not found")

    session = WorkerSession(
        worker_id=data.worker_id,
        task_id=data.task_id,
        agent_id=data.agent_id,
        status="running",
    )
    db.add(session)

    task_result = await db.execute(select(Task).where(Task.id == data.task_id))
    task = task_result.scalars().first()
    if task:
        task.status = "in_progress"

    await db.flush()
    await db.refresh(session)
    return session


@router.put("/sessions/{session_id}", response_model=WorkerSessionResponse)
async def update_session(
    session_id: str, data: WorkerSessionUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(WorkerSession).where(WorkerSession.id == session_id)
    )
    session = result.scalars().first()
    if session is None:
        raise HTTPException(404, "Session not found")

    if data.status is not None:
        session.status = data.status
    if data.last_output is not None:
        session.last_output = data.last_output
    if data.waiting_for_input is not None:
        session.waiting_for_input = data.waiting_for_input
    if data.input_type is not None:
        session.input_type = data.input_type
    if data.input_prompt_text is not None:
        session.input_prompt_text = data.input_prompt_text
    if data.exit_code is not None:
        session.exit_code = data.exit_code

    await db.flush()
    await db.refresh(session)
    return session


# ── Log Streaming ────────────────────────────


@router.post("/sessions/{session_id}/logs", response_model=WorkerLogResponse, status_code=201)
async def add_log(
    session_id: str, data: WorkerLogCreate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(WorkerSession).where(WorkerSession.id == session_id)
    )
    if result.scalars().first() is None:
        raise HTTPException(404, "Session not found")

    log = WorkerLog(session_id=session_id, level=data.level, content=data.content)
    db.add(log)
    await db.flush()
    await db.refresh(log)
    return log


# ── Autonomous Decisions ─────────────────────


@router.post(
    "/sessions/{session_id}/decisions",
    response_model=AutonomousDecisionResponse,
    status_code=201,
)
async def add_decision(
    session_id: str,
    data: AutonomousDecisionCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WorkerSession).where(WorkerSession.id == session_id)
    )
    if result.scalars().first() is None:
        raise HTTPException(404, "Session not found")

    decision = AutonomousDecision(
        session_id=session_id,
        decision=data.decision,
        reason=data.reason,
        auto_resolved=data.auto_resolved,
    )
    db.add(decision)
    await db.flush()
    await db.refresh(decision)
    return decision
