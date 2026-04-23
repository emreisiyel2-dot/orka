import asyncio
from datetime import datetime, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, Agent, ActivityLog
from app.services.agent_simulator import AgentSimulator
from app.services.coordination_service import CoordinationService


class TaskDistributor:
    """Orchestrator task splitting — now with dependency-aware coordination."""

    async def distribute_task(self, task_id: str, db: AsyncSession) -> List[Task]:
        result = await db.execute(select(Task).where(Task.id == task_id))
        original_task = result.scalars().first()
        if original_task is None:
            return []

        # Mark original task as completed (it has been distributed)
        original_task.status = "completed"
        original_task.updated_at = datetime.now(timezone.utc)

        # Use CoordinationService for dependency-aware subtask creation
        service = CoordinationService()
        created_subtasks = await service.create_coordinated_subtasks(original_task, db)

        await db.commit()

        # Only trigger simulation for the FIRST subtask (backend)
        # Remaining subtasks will be triggered when dependencies resolve
        simulator = AgentSimulator()
        for subtask in created_subtasks:
            if subtask.status == "assigned" and subtask.assigned_agent_id:
                asyncio.create_task(
                    simulator.simulate_task_processing_standalone(
                        subtask.id, subtask.assigned_agent_id
                    )
                )
                break  # Only the first assigned task

        return created_subtasks
