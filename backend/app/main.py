import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func

from app.database import init_db, seed_db, async_session
from app.models import Agent, Worker, WorkerSession
from app.api.projects import router as projects_router
from app.api.tasks import router as tasks_router
from app.api.agents import router as agents_router
from app.api.activity import router as activity_router
from app.api.memory import router as memory_router
from app.api.summary import router as summary_router
from app.api.workers import router as workers_router
from app.api.sessions import router as sessions_router
from app.api.messages import router as messages_router
from app.api.dependencies import router as dependencies_router
from app.api.brainstorms import router as brainstorms_router
from app.api.models_api import router as models_api_router
from app.api.quota import router as quota_router
from app.api.budget import router as budget_router
from app.api.routing import router as routing_router
from app.api.goals import router as goals_router
from app.api.runs import router as runs_router
from app.api.research import router as research_router
from app.api.learning import router as learning_router
from app.api.system import router as system_router


# Track connected WebSocket clients
connected_clients: Set[WebSocket] = set()


async def _broadcast_agent_statuses() -> None:
    """Periodically send agent statuses to all connected WebSocket clients."""
    while True:
        await asyncio.sleep(5)
        if not connected_clients:
            continue

        async with async_session() as db:
            result = await db.execute(select(Agent).order_by(Agent.created_at))
            agents = result.scalars().all()
            payload = [
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.type,
                    "status": a.status,
                    "current_task_id": a.current_task_id,
                }
                for a in agents
            ]

        message = json.dumps({"type": "agent_status", "data": payload})
        disconnected: Set[WebSocket] = set()

        for client in connected_clients:
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)

        connected_clients.difference_update(disconnected)


async def _cleanup_stuck_sessions() -> None:
    """Mark sessions stuck in 'running' for over 10 minutes as errors."""
    from datetime import timedelta
    from app.models import WorkerSession, WorkerLog, Task, Agent, ActivityLog

    while True:
        await asyncio.sleep(60)
        try:
            async with async_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
                result = await db.execute(
                    select(WorkerSession).where(
                        WorkerSession.status == "running",
                        WorkerSession.updated_at < cutoff,
                    )
                )
                stuck = result.scalars().all()
                for session in stuck:
                    session.status = "error"
                    session.exit_code = -1
                    db.add(WorkerLog(
                        session_id=session.id,
                        level="error",
                        content="Session timed out — no activity for 10 minutes",
                    ))
                    # Mark task as failed
                    t = await db.execute(select(Task).where(Task.id == session.task_id))
                    task = t.scalars().first()
                    if task and task.status == "in_progress":
                        task.status = "failed"
                if stuck:
                    await db.commit()
        except Exception:
            pass


async def _mark_stale_workers() -> None:
    from datetime import timedelta
    from app.models import Worker

    while True:
        await asyncio.sleep(30)
        try:
            async with async_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
                result = await db.execute(
                    select(Worker).where(
                        Worker.status == "online",
                        Worker.last_heartbeat < cutoff,
                    )
                )
                stale = result.scalars().all()
                for w in stale:
                    w.status = "offline"
                if stale:
                    await db.commit()
        except Exception:
            pass


async def _resolve_dependencies_loop() -> None:
    """Periodically check and satisfy task dependencies."""
    from app.services.coordination_service import CoordinationService

    while True:
        await asyncio.sleep(10)
        try:
            async with async_session() as db:
                service = CoordinationService()
                await service.check_and_resolve_dependencies(db)
                await db.commit()
        except Exception:
            pass


async def _auto_advance_stale_rooms() -> None:
    """Auto-advance brainstorm rooms idle for 60+ seconds."""
    from datetime import timedelta
    from app.models import BrainstormRoom

    while True:
        await asyncio.sleep(30)
        try:
            async with async_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
                result = await db.execute(
                    select(BrainstormRoom).where(
                        BrainstormRoom.status == "brainstorming",
                        BrainstormRoom.updated_at < cutoff,
                        BrainstormRoom.current_round < BrainstormRoom.max_rounds,
                    )
                )
                stale = result.scalars().all()
                for room in stale:
                    room.current_round += 1
                    room.updated_at = datetime.now(timezone.utc)
                    from app.api.brainstorms import _generate_agent_round, _transition_to_refining
                    await _generate_agent_round(room, db)
                    if room.current_round >= room.max_rounds:
                        await _transition_to_refining(room, db)
                if stale:
                    await db.commit()
        except Exception:
            pass


async def _check_quota_resets() -> None:
    """Reset provider quotas when their reset_at time has passed."""
    while True:
        await asyncio.sleep(60)
        try:
            from app.config.model_config import load_config
            from app.services.quota_manager import QuotaManager
            config = load_config()
            mgr = QuotaManager(config)
            async with async_session() as db:
                for state in await mgr.get_all_states(db):
                    if state.reset_at and datetime.now(timezone.utc) >= state.reset_at:
                        await mgr.reset_provider(state.provider, db)
                await db.commit()
        except Exception:
            pass


async def _archive_old_events() -> None:
    """Move RunEvents older than 30 days to run_event_archives."""
    from datetime import timedelta
    from app.models import RunEvent, RunEventArchive

    while True:
        await asyncio.sleep(86400)  # daily
        try:
            async with async_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                old = await db.execute(
                    select(RunEvent).where(RunEvent.created_at < cutoff).limit(500)
                )
                events = old.scalars().all()
                for e in events:
                    db.add(RunEventArchive(
                        id=e.id,
                        run_id=e.run_id,
                        event_type=e.event_type,
                        execution_mode=e.execution_mode,
                        provider=e.provider,
                        model=e.model,
                        message=e.message,
                        metadata_json=e.metadata_json,
                        created_at=e.created_at,
                    ))
                    await db.delete(e)
                if events:
                    await db.commit()
        except Exception:
            pass


async def _snapshot_daily_stats() -> None:
    """Write daily statistics snapshot."""
    from app.models import Run, DailyStats, WorkerSession

    while True:
        await asyncio.sleep(86400)  # daily
        try:
            async with async_session() as db:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                # Check if snapshot already exists for today
                existing = await db.execute(
                    select(DailyStats).where(DailyStats.date == today)
                )
                if existing.scalars().first():
                    continue

                total = await db.execute(
                    select(func.count()).select_from(Run).where(Run.created_at >= today_start)
                )
                failed = await db.execute(
                    select(func.count()).select_from(Run).where(
                        Run.created_at >= today_start, Run.status == "failed"
                    )
                )
                avg_dur = await db.execute(
                    select(func.avg(Run.duration_seconds)).where(
                        Run.created_at >= today_start, Run.duration_seconds.isnot(None)
                    )
                )
                active_cli = await db.execute(
                    select(func.count()).select_from(WorkerSession).where(
                        WorkerSession.status == "running"
                    )
                )

                db.add(DailyStats(
                    date=today,
                    total_runs=total.scalar() or 0,
                    failed_runs=failed.scalar() or 0,
                    avg_duration_seconds=round(avg_dur.scalar() or 0.0, 2),
                    active_cli_sessions=active_cli.scalar() or 0,
                ))
                await db.commit()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize DB and seed agents
    await init_db()
    await seed_db()

    # Start background broadcast task
    broadcast_task = asyncio.create_task(_broadcast_agent_statuses())
    cleanup_task = asyncio.create_task(_cleanup_stuck_sessions())
    stale_worker_task = asyncio.create_task(_mark_stale_workers())
    dep_task = asyncio.create_task(_resolve_dependencies_loop())
    auto_advance_task = asyncio.create_task(_auto_advance_stale_rooms())
    quota_reset_task = asyncio.create_task(_check_quota_resets())
    archive_task = asyncio.create_task(_archive_old_events())
    stats_task = asyncio.create_task(_snapshot_daily_stats())

    yield

    # Shutdown: cancel background tasks
    for t in (broadcast_task, cleanup_task, stale_worker_task, dep_task, auto_advance_task, quota_reset_task, archive_task, stats_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title="ORKA API", lifespan=lifespan)

# CORS middleware (allow all origins for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(agents_router)
app.include_router(activity_router)
app.include_router(memory_router)
app.include_router(summary_router)
app.include_router(workers_router)
app.include_router(sessions_router)
app.include_router(messages_router)
app.include_router(dependencies_router)
app.include_router(brainstorms_router)
app.include_router(models_api_router)
app.include_router(quota_router)
app.include_router(budget_router)
app.include_router(routing_router)
app.include_router(goals_router)
app.include_router(runs_router)
app.include_router(research_router)
app.include_router(learning_router)
app.include_router(system_router)


@app.get("/")
async def root():
    return {"name": "ORKA API", "status": "running"}


@app.get("/health")
async def health():
    async with async_session() as db:
        worker_count = await db.execute(select(func.count()).select_from(Worker).where(Worker.status == "online"))
        active_sessions = await db.execute(select(func.count()).select_from(WorkerSession).where(WorkerSession.status == "running"))
    return {
        "status": "healthy",
        "online_workers": worker_count.scalar(),
        "active_sessions": active_sessions.scalar(),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            # Keep the connection alive by waiting for client messages
            data = await websocket.receive_text()
            # If client sends a message, echo back current agent status
            async with async_session() as db:
                result = await db.execute(select(Agent).order_by(Agent.created_at))
                agents = result.scalars().all()
                payload = [
                    {
                        "id": a.id,
                        "name": a.name,
                        "type": a.type,
                        "status": a.status,
                        "current_task_id": a.current_task_id,
                    }
                    for a in agents
                ]
            await websocket.send_text(
                json.dumps({"type": "agent_status", "data": payload})
            )
    except WebSocketDisconnect:
        connected_clients.discard(websocket)
