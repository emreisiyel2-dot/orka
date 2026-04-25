import asyncio
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_LLM_ENABLED = os.getenv("ORKA_LLM_ENABLED", "false").lower() == "true"

from app.models import Agent, Task, ActivityLog
from app.services.memory_service import MemoryService
from app.services.run_manager import RunManager


class AgentSimulator:
    """Manages simulated agent behavior for task processing."""

    async def simulate_task_processing(
        self, task_id: str, agent_id: str, db: AsyncSession
    ) -> None:
        # 1. Fetch task and agent
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalars().first()
        if task is None:
            return

        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalars().first()
        if agent is None:
            return

        # 2. Set agent status to working
        agent.status = "working"
        agent.current_task_id = task.id

        # 3. Set task status to in_progress
        task.status = "in_progress"
        task.updated_at = datetime.now(timezone.utc)

        # 4. Log activity: started working
        log = ActivityLog(
            project_id=task.project_id,
            agent_id=agent.id,
            action="task_started",
            details=f"Agent {agent.name} started working on: {task.content}",
        )
        db.add(log)
        await db.commit()

        # 4b. Create Run + started event
        run_mgr = RunManager()
        run = await run_mgr.create_run(
            task_id=task.id,
            project_id=task.project_id,
            agent_type=agent.type,
            goal_id=task.goal_id,
            execution_mode="simulated",
            provider="simulated",
            model="simulated",
            db=db,
        )
        await run_mgr.update_status(run.id, "running", db=db)
        await run_mgr.add_event(
            run.id, "started",
            message=f"Agent {agent.name} started run for task",
            execution_mode="simulated",
            provider="simulated",
            db=db,
        )
        await db.commit()

        # 5. Simulate work (3 seconds) — or route to real LLM
        if _LLM_ENABLED:
            pass
        else:
            await asyncio.sleep(3)

        # 6. Set task status to completed
        task.status = "completed"
        task.updated_at = datetime.now(timezone.utc)

        # 7. Set agent status to idle
        agent.status = "idle"
        agent.current_task_id = None

        # 8. Log activity: completed
        log = ActivityLog(
            project_id=task.project_id,
            agent_id=agent.id,
            action="task_completed",
            details=f"Agent {agent.name} completed: {task.content}",
        )
        db.add(log)

        # 8b. Complete run + event
        await run_mgr.add_event(
            run.id, "completed",
            message=f"Task completed successfully",
            db=db,
        )
        await run_mgr.complete_run(run.id, evaluator_status="passed", db=db)

        # 9. Update memory snapshot
        memory_service = MemoryService()
        await memory_service.update_memory(
            task.project_id,
            db,
            last_completed=task.content,
        )

        await db.commit()

    async def simulate_task_processing_standalone(
        self, task_id: str, agent_id: str
    ) -> None:
        """Fire-and-forget wrapper that creates its own database session.

        This is used by the task distributor when spawning background
        simulations via ``asyncio.create_task``.  The caller's session
        may be closed by the time the simulation finishes, so this
        method opens a fresh session for the entire lifecycle of the
        simulated work.
        """
        from app.database import async_session

        async with async_session() as db:
            try:
                await self.simulate_task_processing(task_id, agent_id, db)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
