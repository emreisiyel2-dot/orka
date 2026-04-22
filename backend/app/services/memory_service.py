from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MemorySnapshot


class MemoryService:
    """Manages project memory snapshots (upsert logic)."""

    async def update_memory(
        self,
        project_id: str,
        db: AsyncSession,
        last_completed: Optional[str] = None,
        current_blocker: Optional[str] = None,
        next_step: Optional[str] = None,
    ) -> MemorySnapshot:
        # Try to find an existing snapshot for this project
        result = await db.execute(
            select(MemorySnapshot)
            .where(MemorySnapshot.project_id == project_id)
            .order_by(MemorySnapshot.updated_at.desc())
            .limit(1)
        )
        snapshot = result.scalars().first()

        if snapshot is None:
            snapshot = MemorySnapshot(
                project_id=project_id,
                last_completed=last_completed,
                current_blocker=current_blocker,
                next_step=next_step,
                updated_at=datetime.now(timezone.utc),
            )
            db.add(snapshot)
        else:
            if last_completed is not None:
                snapshot.last_completed = last_completed
            if current_blocker is not None:
                snapshot.current_blocker = current_blocker
            if next_step is not None:
                snapshot.next_step = next_step
            snapshot.updated_at = datetime.now(timezone.utc)

        await db.flush()
        await db.refresh(snapshot)
        return snapshot

    async def get_memory(
        self, project_id: str, db: AsyncSession
    ) -> Optional[MemorySnapshot]:
        result = await db.execute(
            select(MemorySnapshot)
            .where(MemorySnapshot.project_id == project_id)
            .order_by(MemorySnapshot.updated_at.desc())
            .limit(1)
        )
        return result.scalars().first()
