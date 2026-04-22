"""Dashboard-facing API endpoints — view sessions, send input, view decisions."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import WorkerSession, WorkerLog, AutonomousDecision, Task, Agent, Worker
from app.schemas import (
    WorkerSessionResponse,
    WorkerSessionDetail,
    WorkerLogResponse,
    AutonomousDecisionResponse,
    SessionInput,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=List[WorkerSessionResponse])
async def list_sessions(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WorkerSession).order_by(WorkerSession.updated_at.desc())
    if status:
        stmt = stmt.where(WorkerSession.status == status)
    if project_id:
        task_sub = select(Task.id).where(Task.project_id == project_id)
        stmt = stmt.where(WorkerSession.task_id.in_(task_sub))

    result = await db.execute(stmt.limit(100))
    return result.scalars().all()


@router.get("/{session_id}", response_model=WorkerSessionDetail)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WorkerSession).where(WorkerSession.id == session_id)
    )
    session = result.scalars().first()
    if session is None:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/{session_id}/input", response_model=WorkerSessionResponse)
async def send_input(
    session_id: str, data: SessionInput, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(WorkerSession).where(WorkerSession.id == session_id)
    )
    session = result.scalars().first()
    if session is None:
        raise HTTPException(404, "Session not found")
    if not session.waiting_for_input:
        raise HTTPException(400, "Session is not waiting for input")

    session.last_output = f"[USER INPUT] {data.input_value}"
    session.waiting_for_input = False
    session.input_type = "none"
    session.input_prompt_text = None
    session.status = "running"

    log = WorkerLog(
        session_id=session.id,
        level="info",
        content=f"User provided input: {data.input_value}",
    )
    db.add(log)
    await db.flush()
    await db.refresh(session)
    return session


@router.get("/{session_id}/logs", response_model=List[WorkerLogResponse])
async def get_session_logs(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WorkerLog)
        .where(WorkerLog.session_id == session_id)
        .order_by(WorkerLog.timestamp.desc())
        .limit(200)
    )
    return result.scalars().all()


@router.get(
    "/{session_id}/decisions", response_model=List[AutonomousDecisionResponse]
)
async def get_session_decisions(
    session_id: str, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(AutonomousDecision)
        .where(AutonomousDecision.session_id == session_id)
        .order_by(AutonomousDecision.timestamp.desc())
    )
    return result.scalars().all()
