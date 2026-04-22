from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ActivityLog
from app.schemas import ActivityLogResponse

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=List[ActivityLogResponse])
async def list_activity(
    project_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ActivityLog).order_by(ActivityLog.timestamp.desc()).limit(50)
    if project_id:
        stmt = stmt.where(ActivityLog.project_id == project_id)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return logs
