from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MemorySnapshot
from app.schemas import MemorySnapshotCreate, MemorySnapshotResponse
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/{project_id}", response_model=MemorySnapshotResponse)
async def get_memory(project_id: str, db: AsyncSession = Depends(get_db)):
    service = MemoryService()
    snapshot = await service.get_memory(project_id, db)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No memory snapshot found for this project")
    return snapshot


@router.post("/{project_id}", response_model=MemorySnapshotResponse, status_code=201)
async def create_or_update_memory(
    project_id: str,
    data: MemorySnapshotCreate,
    db: AsyncSession = Depends(get_db),
):
    service = MemoryService()
    snapshot = await service.update_memory(
        project_id,
        db,
        last_completed=data.last_completed,
        current_blocker=data.current_blocker,
        next_step=data.next_step,
    )
    await db.flush()
    return snapshot
