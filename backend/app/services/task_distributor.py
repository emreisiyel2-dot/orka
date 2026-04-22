import asyncio
from datetime import datetime, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, Agent, ActivityLog
from app.services.agent_simulator import AgentSimulator


# Mapping from subtask role to agent type
SUBTASK_DEFS = [
    {"suffix": "Backend implementation for: {}", "agent_type": "backend"},
    {"suffix": "Frontend implementation for: {}", "agent_type": "frontend"},
    {"suffix": "QA testing for: {}", "agent_type": "qa"},
    {"suffix": "Documentation for: {}", "agent_type": "docs"},
]


class TaskDistributor:
    """Orchestrator task splitting and distribution logic."""

    async def distribute_task(self, task_id: str, db: AsyncSession) -> List[Task]:
        # Fetch the original task
        result = await db.execute(select(Task).where(Task.id == task_id))
        original_task = result.scalars().first()
        if original_task is None:
            return []

        # Mark original task as completed (it has been distributed)
        original_task.status = "completed"
        original_task.updated_at = datetime.now(timezone.utc)

        # Fetch agents by type for assignment
        result = await db.execute(select(Agent))
        all_agents = result.scalars().all()
        agents_by_type = {a.type: a for a in all_agents}

        # Create subtasks based on agent types
        created_subtasks: List[Task] = []
        for definition in SUBTASK_DEFS:
            agent_type = definition["agent_type"]
            agent = agents_by_type.get(agent_type)
            if agent is None:
                continue

            subtask_content = definition["suffix"].format(original_task.content)
            subtask = Task(
                project_id=original_task.project_id,
                content=subtask_content,
                status="assigned",
                assigned_agent_id=agent.id,
                parent_task_id=original_task.id,
            )
            db.add(subtask)
            created_subtasks.append(subtask)

        await db.flush()

        # Refresh subtasks to get their IDs
        refreshed: List[Task] = []
        for subtask in created_subtasks:
            await db.refresh(subtask)
            refreshed.append(subtask)

        # Log the distribution activity
        log = ActivityLog(
            project_id=original_task.project_id,
            agent_id=agents_by_type.get("orchestrator", all_agents[0]).id if all_agents else None,
            action="task_distributed",
            details=f"Orchestrator distributed task into {len(refreshed)} subtasks: {original_task.content}",
        )
        db.add(log)
        await db.commit()

        # Trigger agent simulation for each subtask (fire-and-forget).
        # Each simulation runs with its own independent database session
        # so it is fully self-contained and does not depend on the request session.
        simulator = AgentSimulator()
        for subtask in refreshed:
            if subtask.assigned_agent_id:
                asyncio.create_task(
                    simulator.simulate_task_processing_standalone(
                        subtask.id, subtask.assigned_agent_id
                    )
                )

        return refreshed
