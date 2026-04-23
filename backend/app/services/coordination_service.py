"""Coordination engine — dependency-aware task distribution and agent collaboration."""

import asyncio
from datetime import datetime, timezone
from typing import List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Task, AgentMessage, TaskDependency, ActivityLog, MemorySnapshot
from app.services.memory_service import MemoryService
from app.services.agent_simulator import AgentSimulator


# Ordered pipeline: each entry defines a subtask and what it depends on
PIPELINE = [
    {"suffix": "Backend implementation for: {}", "agent_type": "backend", "depends_on": None},
    {"suffix": "Frontend implementation for: {}", "agent_type": "frontend", "depends_on": "backend"},
    {"suffix": "QA testing for: {}", "agent_type": "qa", "depends_on": "frontend"},
    {"suffix": "Documentation for: {}", "agent_type": "docs", "depends_on": "qa"},
]


class CoordinationService:
    """Manages coordinated multi-agent task execution with dependencies."""

    async def create_coordinated_subtasks(
        self, parent_task: Task, db: AsyncSession
    ) -> List[Task]:
        all_agents = (await db.execute(select(Agent))).scalars().all()
        agents_by_type = {a.type: a for a in all_agents}
        orchestrator = agents_by_type.get("orchestrator", all_agents[0] if all_agents else None)

        # Create subtasks
        created: List[Task] = []
        subtask_by_type: dict[str, Task] = {}

        for entry in PIPELINE:
            agent = agents_by_type.get(entry["agent_type"])
            if agent is None:
                continue

            content = entry["suffix"].format(parent_task.content)
            status = "assigned" if entry["depends_on"] is None else "pending"

            subtask = Task(
                project_id=parent_task.project_id,
                content=content,
                status=status,
                assigned_agent_id=agent.id if status == "assigned" else None,
                parent_task_id=parent_task.id,
            )
            db.add(subtask)
            created.append(subtask)
            subtask_by_type[entry["agent_type"]] = subtask

        await db.flush()
        for s in created:
            await db.refresh(s)

        # Create dependencies
        for entry in PIPELINE:
            if entry["depends_on"] is None:
                continue
            dep_task = subtask_by_type.get(entry["depends_on"])
            this_task = subtask_by_type.get(entry["agent_type"])
            if dep_task and this_task:
                dep = TaskDependency(
                    task_id=this_task.id,
                    depends_on_task_id=dep_task.id,
                )
                db.add(dep)

        # Create initial handoff message: Orchestrator → Backend
        backend_task = subtask_by_type.get("backend")
        backend_agent = agents_by_type.get("backend")
        if orchestrator and backend_agent and backend_task:
            msg = AgentMessage(
                project_id=parent_task.project_id,
                task_id=backend_task.id,
                from_agent_id=orchestrator.id,
                to_agent_id=backend_agent.id,
                message_type="handoff",
                content=f"Start implementation for: {parent_task.content}",
            )
            db.add(msg)

        # Log coordination
        if orchestrator:
            log = ActivityLog(
                project_id=parent_task.project_id,
                agent_id=orchestrator.id,
                action="task_coordinated",
                details=f"Orchestrator created {len(created)} coordinated subtasks with dependencies",
            )
            db.add(log)

        await db.flush()
        return created

    async def check_and_resolve_dependencies(self, db: AsyncSession) -> None:
        """Check all pending deps and satisfy those whose prerequisite is complete."""
        result = await db.execute(
            select(TaskDependency).where(TaskDependency.status == "pending")
        )
        pending = result.scalars().all()

        for dep in pending:
            dep_task = (await db.execute(select(Task).where(Task.id == dep.depends_on_task_id))).scalars().first()
            if dep_task and dep_task.status == "completed":
                dep.status = "satisfied"
                dep.satisfied_at = datetime.now(timezone.utc)

                # Check if the dependent task has ALL deps satisfied
                remaining = (await db.execute(
                    select(TaskDependency).where(
                        TaskDependency.task_id == dep.task_id,
                        TaskDependency.status == "pending",
                    )
                )).scalars().first()

                if remaining is None:
                    task = (await db.execute(select(Task).where(Task.id == dep.task_id))).scalars().first()
                    if task and task.status == "pending":
                        task.status = "assigned"

                        # Find the agent for this task
                        agent = None
                        if task.assigned_agent_id:
                            agent = (await db.execute(select(Agent).where(Agent.id == task.assigned_agent_id))).scalars().first()

                        # Log unblock
                        db.add(ActivityLog(
                            project_id=task.project_id,
                            action="task_unblocked",
                            details=f"Task '{task.content}' unblocked — starting execution",
                        ))

                        # Create handoff message
                        # Find orchestrator as sender
                        orch = (await db.execute(select(Agent).where(Agent.type == "orchestrator"))).scalars().first()
                        if orch and agent:
                            db.add(AgentMessage(
                                project_id=task.project_id,
                                task_id=task.id,
                                from_agent_id=orch.id,
                                to_agent_id=agent.id,
                                message_type="handoff",
                                content=f"Dependency satisfied — start: {task.content}",
                            ))

                        # Trigger agent simulation for the newly unblocked task
                        if agent:
                            simulator = AgentSimulator()
                            asyncio.create_task(
                                simulator.simulate_task_processing_standalone(task.id, agent.id)
                            )

    async def send_handoff(
        self, from_agent_id: str, to_agent_id: str, task_id: str,
        project_id: str, content: str, db: AsyncSession
    ) -> AgentMessage:
        msg = AgentMessage(
            project_id=project_id,
            task_id=task_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            message_type="handoff",
            content=content,
        )
        db.add(msg)
        db.add(ActivityLog(
            project_id=project_id,
            agent_id=from_agent_id,
            action="agent_handoff",
            details=content[:200],
        ))
        await db.flush()
        await db.refresh(msg)
        return msg

    async def report_blocker(
        self, agent_id: str, task_id: str, project_id: str,
        content: str, db: AsyncSession
    ) -> AgentMessage:
        msg = AgentMessage(
            project_id=project_id,
            task_id=task_id,
            from_agent_id=agent_id,
            to_agent_id=agent_id,
            message_type="blocker",
            content=content,
        )
        db.add(msg)
        db.add(ActivityLog(
            project_id=project_id,
            agent_id=agent_id,
            action="blocker_reported",
            details=content[:200],
        ))
        # Update memory with blocker
        ms = MemoryService()
        await ms.update_memory(project_id, db, current_blocker=content)
        await db.flush()
        await db.refresh(msg)
        return msg

    async def generate_merged_summary(self, project_id: str, db: AsyncSession) -> dict:
        tasks = (await db.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
        total = len(tasks)
        completed = sum(1 for t in tasks if t.status == "completed")
        in_progress = sum(1 for t in tasks if t.status in ("assigned", "in_progress"))
        pending = sum(1 for t in tasks if t.status == "pending")
        failed = sum(1 for t in tasks if t.status == "failed")

        agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
        agent_list = [{"name": a.name, "type": a.type, "status": a.status} for a in agents]

        blockers = (await db.execute(
            select(AgentMessage).where(
                AgentMessage.project_id == project_id,
                AgentMessage.message_type == "blocker",
                AgentMessage.status != "acted_on",
            )
        )).scalars().all()

        pending_handoffs = (await db.execute(
            select(AgentMessage).where(
                AgentMessage.project_id == project_id,
                AgentMessage.message_type == "handoff",
                AgentMessage.status == "pending",
            )
        )).scalars().all()

        all_deps = (await db.execute(
            select(TaskDependency).where(
                TaskDependency.task_id.in_(select(Task.id).where(Task.project_id == project_id))
            )
        )).scalars().all()
        pending_deps = sum(1 for d in all_deps if d.status == "pending")

        recent_msgs = (await db.execute(
            select(AgentMessage).where(AgentMessage.project_id == project_id)
            .order_by(AgentMessage.created_at.desc()).limit(5)
        )).scalars().all()

        ms = MemoryService()
        memory = await ms.get_memory(project_id, db)

        # Determine if workflow is complete
        subtasks = [t for t in tasks if t.parent_task_id is not None]
        workflow_complete = len(subtasks) > 0 and all(t.status == "completed" for t in subtasks)

        # Build summary text
        parts = []
        if total == 0:
            parts.append("No tasks yet.")
        else:
            parts.append(f"{completed}/{total} tasks completed.")
        if blockers:
            parts.append(f"{len(blockers)} active blocker(s).")
        if workflow_complete:
            parts.append("Workflow complete — all subtasks finished.")
        elif in_progress > 0:
            parts.append(f"{in_progress} task(s) in progress.")
        else:
            parts.append("All agents idle.")

        return {
            "project_id": project_id,
            "total_tasks": total,
            "completed_tasks": completed,
            "in_progress_tasks": in_progress,
            "pending_tasks": pending,
            "failed_tasks": failed,
            "active_blockers": len(blockers),
            "pending_handoffs": len(pending_handoffs),
            "pending_dependencies": pending_deps,
            "dependency_status": "all_satisfied" if pending_deps == 0 else "has_pending",
            "agent_messages_count": (await db.execute(
                select(func.count()).select_from(AgentMessage).where(AgentMessage.project_id == project_id)
            )).scalar() or 0,
            "workflow_complete": workflow_complete,
            "summary_text": " ".join(parts),
            "agents": agent_list,
            "recent_messages": [
                {
                    "from": m.from_agent.name if m.from_agent else "?",
                    "to": m.to_agent.name if m.to_agent else "?",
                    "type": m.message_type,
                    "content": m.content[:80],
                }
                for m in recent_msgs
            ],
            "memory": {
                "last_completed": memory.last_completed,
                "current_blocker": memory.current_blocker,
                "next_step": memory.next_step,
            } if memory else None,
        }
