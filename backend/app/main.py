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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize DB and seed agents
    await init_db()
    await seed_db()

    # Start background broadcast task
    broadcast_task = asyncio.create_task(_broadcast_agent_statuses())
    cleanup_task = asyncio.create_task(_cleanup_stuck_sessions())
    stale_worker_task = asyncio.create_task(_mark_stale_workers())

    yield

    # Shutdown: cancel background tasks
    for t in (broadcast_task, cleanup_task, stale_worker_task):
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
