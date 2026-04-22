import asyncio
import json
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.database import init_db, seed_db, async_session
from app.models import Agent
from app.api.projects import router as projects_router
from app.api.tasks import router as tasks_router
from app.api.agents import router as agents_router
from app.api.activity import router as activity_router
from app.api.memory import router as memory_router
from app.api.summary import router as summary_router


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize DB and seed agents
    await init_db()
    await seed_db()

    # Start background broadcast task
    broadcast_task = asyncio.create_task(_broadcast_agent_statuses())

    yield

    # Shutdown: cancel background task
    broadcast_task.cancel()
    try:
        await broadcast_task
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


@app.get("/")
async def root():
    return {"name": "ORKA API", "status": "running"}


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
