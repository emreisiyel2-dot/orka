"""Brainstorm room API — CRUD, advance, message, skip, spawn, skills."""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    BrainstormRoom,
    BrainstormMessage,
    BrainstormAgent,
    BrainstormSkill,
    Project,
    Task,
    TaskDependency,
    MemorySnapshot,
    ActivityLog,
)
from app.schemas import (
    BrainstormRoomCreate,
    BrainstormRoomResponse,
    BrainstormRoomDetail,
    BrainstormAgentResponse,
    BrainstormMessageResponse,
    BrainstormSkillResponse,
    BrainstormUserMessage,
    BrainstormSkillUpdate,
    BrainstormModeUpdate,
    SpawnPlan,
)
from app.services.brainstorm_agent import (
    SimulatedBrainstormAgent,
    AGENT_ORDER,
    AGENT_NAMES,
)
from app.services.skill_detector import SkillDetector
from app.services.spawn_plan_generator import SpawnPlanGenerator
from app.services.brainstorm_context_bridge import BrainstormContextBridge

router = APIRouter(prefix="/api/brainstorms", tags=["brainstorms"])

_brainstorm_agent = SimulatedBrainstormAgent()
_skill_detector = SkillDetector()
_plan_generator = SpawnPlanGenerator()
_context_bridge = BrainstormContextBridge()


def _room_to_response(room: BrainstormRoom) -> dict:
    return {
        "id": room.id,
        "title": room.title,
        "idea_text": room.idea_text,
        "status": room.status,
        "current_round": room.current_round,
        "max_rounds": room.max_rounds,
        "mode": room.mode,
        "synthesis": room.synthesis,
        "project_id": room.project_id,
        "spawn_plan": room.spawn_plan,
        "created_at": room.created_at,
        "updated_at": room.updated_at,
    }


def _agent_to_response(agent: BrainstormAgent) -> dict:
    return {
        "id": agent.id,
        "agent_type": agent.agent_type,
        "agent_name": agent.agent_name,
        "status": agent.status,
        "turn_order": agent.turn_order,
    }


def _msg_to_response(msg: BrainstormMessage) -> dict:
    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "agent_id": msg.agent_id,
        "agent_type": msg.agent_type,
        "role": msg.role,
        "content": msg.content,
        "message_type": msg.message_type,
        "round_number": msg.round_number,
        "created_at": msg.created_at,
    }


def _skill_to_response(skill: BrainstormSkill) -> dict:
    return {
        "id": skill.id,
        "skill_name": skill.skill_name,
        "description": skill.description,
        "relevance_reason": skill.relevance_reason,
        "status": skill.status,
    }


async def _get_room_or_404(room_id: str, db: AsyncSession) -> BrainstormRoom:
    result = await db.execute(
        select(BrainstormRoom).where(BrainstormRoom.id == room_id)
    )
    room = result.scalars().first()
    if room is None:
        raise HTTPException(status_code=404, detail="Brainstorm room not found")
    return room


async def _create_room_agents(room: BrainstormRoom, db: AsyncSession) -> None:
    for i, agent_type in enumerate(AGENT_ORDER):
        agent = BrainstormAgent(
            room_id=room.id,
            agent_type=agent_type,
            agent_name=AGENT_NAMES[agent_type],
            turn_order=i,
        )
        db.add(agent)
    await db.flush()


async def _create_initial_skills(room: BrainstormRoom, db: AsyncSession) -> None:
    detected = _skill_detector.detect(room.idea_text)
    for skill in detected:
        db.add(BrainstormSkill(
            room_id=room.id,
            skill_name=skill.name,
            description=skill.description,
            relevance_reason=skill.relevance_reason,
        ))
    await db.flush()


async def _generate_agent_round(room: BrainstormRoom, db: AsyncSession) -> list:
    agents_result = await db.execute(
        select(BrainstormAgent)
        .where(BrainstormAgent.room_id == room.id, BrainstormAgent.status == "active")
        .order_by(BrainstormAgent.turn_order)
    )
    agents = agents_result.scalars().all()

    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room.id)
        .order_by(BrainstormMessage.created_at)
    )
    conversation = [
        {"content": m.content, "message_type": m.message_type, "agent_type": m.agent_type}
        for m in msgs_result.scalars().all()
    ]

    new_messages = []
    for agent in agents:
        response = _brainstorm_agent.generate_response(
            agent_type=agent.agent_type,
            idea_text=room.idea_text,
            conversation=conversation,
            round_number=room.current_round,
            mode=room.mode,
        )
        msg = BrainstormMessage(
            room_id=room.id,
            agent_id=agent.id,
            agent_type=agent.agent_type,
            role="agent",
            content=response.content,
            message_type=response.message_type,
            round_number=room.current_round,
        )
        db.add(msg)
        new_messages.append(msg)
        conversation.append({
            "content": response.content,
            "message_type": response.message_type,
            "agent_type": agent.agent_type,
        })

    await db.flush()
    return new_messages


async def _transition_to_refining(room: BrainstormRoom, db: AsyncSession) -> None:
    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room.id)
        .order_by(BrainstormMessage.created_at)
    )
    messages = msgs_result.scalars().all()
    message_dicts = [
        {"content": m.content, "message_type": m.message_type, "agent_type": m.agent_type}
        for m in messages
    ]

    spawn_plan = _plan_generator.generate(room.idea_text, message_dicts)
    room.spawn_plan = spawn_plan.model_dump_json()
    room.status = "ready_to_spawn"
    room.updated_at = datetime.now(timezone.utc)


async def _generate_synthesis(room: BrainstormRoom, db: AsyncSession) -> None:
    """Generate synthesis summary when soft limit reached. Does NOT force transition."""
    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room.id)
        .order_by(BrainstormMessage.created_at)
    )
    messages = msgs_result.scalars().all()

    # Extract key data from messages
    decisions = [m for m in messages if m.message_type == "suggestion"]
    risks = [m for m in messages if m.message_type == "risk"]
    questions = [m for m in messages if m.message_type == "question"]

    synthesis = {
        "round_reached": room.current_round,
        "total_messages": len(messages),
        "key_decisions": [m.content[:100] for m in decisions[:5]],
        "risks_identified": [m.content[:100] for m in risks[:5]],
        "open_questions": [m.content[:100] for m in questions[:3]],
        "suggested_actions": [
            "Continue Brainstorming",
            "Deep Dive This Topic",
            "Generate Alternative Approaches",
            "Finalize & Spawn Project",
        ],
        "summary_text": (
            f"Round {room.current_round} complete. "
            f"{len(decisions)} decisions proposed, "
            f"{len(risks)} risks identified, "
            f"{len(questions)} open questions remain."
        ),
    }

    import json as _json
    room.synthesis = _json.dumps(synthesis)
    room.updated_at = datetime.now(timezone.utc)


# ── CRUD ──────────────────────────────────────────────


@router.post("", response_model=BrainstormRoomResponse, status_code=201)
async def create_room(
    payload: BrainstormRoomCreate,
    db: AsyncSession = Depends(get_db),
):
    title = payload.title or payload.idea_text[:80]
    room = BrainstormRoom(
        title=title,
        idea_text=payload.idea_text,
        mode=payload.mode,
    )
    db.add(room)
    await db.flush()
    await db.refresh(room)

    await _create_room_agents(room, db)
    await _create_initial_skills(room, db)

    await db.refresh(room)
    return _room_to_response(room)


@router.get("", response_model=list[BrainstormRoomResponse])
async def list_rooms(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BrainstormRoom).order_by(BrainstormRoom.created_at.desc())
    if status:
        stmt = stmt.where(BrainstormRoom.status == status)
    result = await db.execute(stmt)
    rooms = result.scalars().all()
    return [_room_to_response(r) for r in rooms]


@router.get("/{room_id}", response_model=BrainstormRoomDetail)
async def get_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room_id)
        .order_by(BrainstormMessage.created_at)
    )
    agents_result = await db.execute(
        select(BrainstormAgent)
        .where(BrainstormAgent.room_id == room_id)
        .order_by(BrainstormAgent.turn_order)
    )
    skills_result = await db.execute(
        select(BrainstormSkill).where(BrainstormSkill.room_id == room_id)
    )

    resp = _room_to_response(room)
    resp["messages"] = [_msg_to_response(m) for m in msgs_result.scalars().all()]
    resp["agents"] = [_agent_to_response(a) for a in agents_result.scalars().all()]
    resp["skills"] = [_skill_to_response(s) for s in skills_result.scalars().all()]
    return resp


@router.delete("/{room_id}")
async def delete_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)
    await db.delete(room)
    return {"deleted": True}


# ── Flow Control ──────────────────────────────────────


@router.post("/{room_id}/advance", response_model=list[BrainstormMessageResponse])
async def advance_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")
    if room.status in ("refining", "ready_to_spawn"):
        raise HTTPException(400, "Room is past brainstorming phase")

    room.current_round += 1
    room.updated_at = datetime.now(timezone.utc)

    new_messages = await _generate_agent_round(room, db)

    # Soft limit: when round >= max_rounds, generate synthesis suggestion
    if room.current_round >= room.max_rounds and not room.synthesis:
        await _generate_synthesis(room, db)

    await db.flush()
    return [_msg_to_response(m) for m in new_messages]


@router.post("/{room_id}/message", response_model=list[BrainstormMessageResponse])
async def send_message(
    room_id: str,
    payload: BrainstormUserMessage,
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")
    if room.status in ("refining", "ready_to_spawn"):
        raise HTTPException(400, "Room is past brainstorming phase")

    user_msg = BrainstormMessage(
        room_id=room.id,
        agent_id=None,
        agent_type=None,
        role="user",
        content=payload.content,
        message_type="idea",
        round_number=room.current_round,
    )
    db.add(user_msg)
    await db.flush()

    results = [user_msg]

    if payload.target_agent_type:
        agent_result = await db.execute(
            select(BrainstormAgent).where(
                BrainstormAgent.room_id == room.id,
                BrainstormAgent.agent_type == payload.target_agent_type,
                BrainstormAgent.status == "active",
            )
        )
        agent = agent_result.scalars().first()
        if agent:
            response = _brainstorm_agent.generate_response(
                agent_type=agent.agent_type,
                idea_text=room.idea_text,
                conversation=[{"content": payload.content}],
                round_number=room.current_round,
                mode=room.mode,
            )
            agent_msg = BrainstormMessage(
                room_id=room.id,
                agent_id=agent.id,
                agent_type=agent.agent_type,
                role="agent",
                content=response.content,
                message_type="response",
                round_number=room.current_round,
            )
            db.add(agent_msg)
            results.append(agent_msg)

    room.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return [_msg_to_response(m) for m in results]


@router.post("/{room_id}/skip", response_model=BrainstormRoomResponse)
async def skip_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    if room.status == "brainstorming":
        await _transition_to_refining(room, db)
    elif room.status == "refining":
        room.status = "ready_to_spawn"

    room.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(room)
    return _room_to_response(room)


# ── Mode & Synthesis ──────────────────────────────────


@router.put("/{room_id}/mode", response_model=BrainstormRoomResponse)
async def update_mode(
    room_id: str,
    payload: BrainstormModeUpdate,
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")

    valid_modes = ("normal", "deep_dive", "exploration", "decision")
    if payload.mode not in valid_modes:
        raise HTTPException(400, f"Invalid mode. Use: {', '.join(valid_modes)}")

    room.mode = payload.mode
    room.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(room)
    return _room_to_response(room)


@router.post("/{room_id}/synthesize")
async def synthesize_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")

    await _generate_synthesis(room, db)
    await db.flush()

    import json as _json
    return _json.loads(room.synthesis) if room.synthesis else {}


# ── Spawn ─────────────────────────────────────────────


@router.post("/{room_id}/spawn")
async def spawn_project(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")

    if room.status in ("brainstorming", "refining"):
        if not room.spawn_plan:
            await _transition_to_refining(room, db)

    plan_data = json.loads(room.spawn_plan) if room.spawn_plan else {}
    plan = SpawnPlan(**plan_data) if plan_data else None

    project_name = plan.project_name if plan else room.title
    project_desc = plan.description if plan else room.idea_text
    project = Project(name=project_name, description=project_desc)
    db.add(project)
    await db.flush()
    await db.refresh(project)

    if plan:
        task_map = {}
        for task_def in plan.tasks:
            task = Task(
                project_id=project.id,
                content=task_def.title,
                status="pending",
            )
            db.add(task)
            await db.flush()
            await db.refresh(task)
            task_map[task_def.title] = task

        for task_def in plan.tasks:
            if task_def.depends_on:
                child_task = task_map.get(task_def.title)
                for dep_title in task_def.depends_on:
                    parent_task = task_map.get(dep_title)
                    if child_task and parent_task:
                        db.add(TaskDependency(
                            task_id=child_task.id,
                            depends_on_task_id=parent_task.id,
                        ))

    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room.id)
        .order_by(BrainstormMessage.created_at)
    )
    messages = msgs_result.scalars().all()
    message_dicts = [
        {"content": m.content, "message_type": m.message_type, "agent_type": m.agent_type, "role": m.role}
        for m in messages
    ]

    context_summary = _context_bridge.generate_summary(
        idea_text=room.idea_text,
        messages=message_dicts,
        spawn_plan=plan_data,
    )

    memory = MemorySnapshot(
        project_id=project.id,
        last_completed="Project spawned from brainstorm",
        current_blocker="",
        next_step=context_summary,
    )
    db.add(memory)

    room.status = "spawned"
    room.project_id = project.id
    room.updated_at = datetime.now(timezone.utc)

    db.add(ActivityLog(
        project_id=project.id,
        action="project_spawned",
        details=f"Project spawned from brainstorm room: {room.title}",
    ))

    await db.flush()
    return {"project_id": project.id, "room": _room_to_response(room)}


# ── Skills ────────────────────────────────────────────


@router.get("/{room_id}/skills", response_model=list[BrainstormSkillResponse])
async def list_skills(room_id: str, db: AsyncSession = Depends(get_db)):
    await _get_room_or_404(room_id, db)
    result = await db.execute(
        select(BrainstormSkill).where(BrainstormSkill.room_id == room_id)
    )
    return [_skill_to_response(s) for s in result.scalars().all()]


@router.put("/{room_id}/skills/{skill_id}", response_model=BrainstormSkillResponse)
async def update_skill(
    room_id: str,
    skill_id: str,
    payload: BrainstormSkillUpdate,
    db: AsyncSession = Depends(get_db),
):
    await _get_room_or_404(room_id, db)
    result = await db.execute(
        select(BrainstormSkill).where(
            BrainstormSkill.id == skill_id,
            BrainstormSkill.room_id == room_id,
        )
    )
    skill = result.scalars().first()
    if skill is None:
        raise HTTPException(404, "Skill not found")

    if payload.status not in ("accepted", "rejected", "suggested"):
        raise HTTPException(400, "Invalid status. Use: accepted, rejected, suggested")

    skill.status = payload.status
    await db.flush()
    return _skill_to_response(skill)
