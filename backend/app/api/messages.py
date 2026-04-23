from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AgentMessage, Agent, Task, ActivityLog
from app.schemas import AgentMessageCreate, AgentMessageResponse

router = APIRouter(prefix="/api/messages", tags=["messages"])


async def _populate_agent_names(msg: AgentMessage) -> dict:
    """Build a response dict with agent names filled from relationships."""
    return {
        "id": msg.id,
        "project_id": msg.project_id,
        "task_id": msg.task_id,
        "from_agent_id": msg.from_agent_id,
        "to_agent_id": msg.to_agent_id,
        "message_type": msg.message_type,
        "content": msg.content,
        "context": msg.context,
        "status": msg.status,
        "created_at": msg.created_at,
        "from_agent_name": msg.from_agent.name if msg.from_agent else None,
        "to_agent_name": msg.to_agent.name if msg.to_agent else None,
    }


@router.post("", response_model=AgentMessageResponse, status_code=201)
async def create_message(
    payload: AgentMessageCreate,
    db: AsyncSession = Depends(get_db),
):
    # Validate from_agent_id
    result = await db.execute(select(Agent).where(Agent.id == payload.from_agent_id))
    from_agent = result.scalars().first()
    if from_agent is None:
        raise HTTPException(status_code=400, detail="from_agent_id not found")

    # Validate to_agent_id
    result = await db.execute(select(Agent).where(Agent.id == payload.to_agent_id))
    to_agent = result.scalars().first()
    if to_agent is None:
        raise HTTPException(status_code=400, detail="to_agent_id not found")

    # Create the message
    msg = AgentMessage(
        project_id=payload.project_id,
        task_id=payload.task_id,
        from_agent_id=payload.from_agent_id,
        to_agent_id=payload.to_agent_id,
        message_type=payload.message_type,
        content=payload.content,
        context=payload.context,
        status="pending",
    )
    db.add(msg)
    await db.flush()
    await db.refresh(msg)

    # Create an ActivityLog entry
    content_preview = payload.content[:80]
    log = ActivityLog(
        project_id=payload.project_id,
        agent_id=payload.from_agent_id,
        action="agent_message",
        details=(
            f"{from_agent.name} → {to_agent.name}: "
            f"{payload.message_type} — {content_preview}"
        ),
    )
    db.add(log)

    # Re-refresh to load relationships after flush
    await db.refresh(msg)
    return await _populate_agent_names(msg)


@router.get("", response_model=List[AgentMessageResponse])
async def list_messages(
    project_id: str = Query(...),
    task_id: Optional[str] = Query(None),
    message_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.project_id == project_id)
        .order_by(AgentMessage.created_at.desc())
        .limit(100)
    )
    if task_id is not None:
        stmt = stmt.where(AgentMessage.task_id == task_id)
    if message_type is not None:
        stmt = stmt.where(AgentMessage.message_type == message_type)
    if status is not None:
        stmt = stmt.where(AgentMessage.status == status)

    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [await _populate_agent_names(m) for m in messages]


@router.get("/agent/{agent_id}/inbox", response_model=List[AgentMessageResponse])
async def get_agent_inbox(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.to_agent_id == agent_id)
        .order_by(AgentMessage.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [await _populate_agent_names(m) for m in messages]


@router.get("/agent/{agent_id}/outbox", response_model=List[AgentMessageResponse])
async def get_agent_outbox(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.from_agent_id == agent_id)
        .order_by(AgentMessage.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [await _populate_agent_names(m) for m in messages]


@router.put("/{message_id}/read", response_model=AgentMessageResponse)
async def mark_message_read(
    message_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentMessage).where(AgentMessage.id == message_id)
    )
    msg = result.scalars().first()
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.status = "read"
    await db.flush()
    await db.refresh(msg)
    return await _populate_agent_names(msg)


@router.put("/{message_id}/acted", response_model=AgentMessageResponse)
async def mark_message_acted(
    message_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentMessage).where(AgentMessage.id == message_id)
    )
    msg = result.scalars().first()
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.status = "acted_on"
    await db.flush()
    await db.refresh(msg)
    return await _populate_agent_names(msg)


@router.get("/project/{project_id}/blockers", response_model=List[AgentMessageResponse])
async def get_project_blockers(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.project_id == project_id)
        .where(AgentMessage.message_type == "blocker")
        .where(AgentMessage.status != "acted_on")
        .order_by(AgentMessage.created_at.desc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [await _populate_agent_names(m) for m in messages]


@router.get("/project/{project_id}/handoffs", response_model=List[AgentMessageResponse])
async def get_project_handoffs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.project_id == project_id)
        .where(AgentMessage.message_type == "handoff")
        .where(AgentMessage.status == "pending")
        .order_by(AgentMessage.created_at.desc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [await _populate_agent_names(m) for m in messages]
