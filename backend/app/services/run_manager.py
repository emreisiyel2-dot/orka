import json
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, Run, RunEvent, Task
from app.schemas import GoalProgressResponse, AgentPerformanceResponse


class RunManager:
    """Orchestrates Run lifecycle, events, and performance queries."""

    async def create_run(
        self,
        task_id: str,
        project_id: str,
        agent_type: str,
        goal_id: str | None = None,
        execution_mode: str = "simulated",
        provider: str = "unknown",
        model: str = "unknown",
        worker_session_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> Run:
        # Determine retry_count from previous runs on the same task
        retry_count = 0
        if db is not None:
            result = await db.execute(
                select(func.count()).select_from(Run).where(Run.task_id == task_id)
            )
            retry_count = result.scalar() or 0

        run = Run(
            task_id=task_id,
            goal_id=goal_id,
            project_id=project_id,
            agent_type=agent_type,
            execution_mode=execution_mode,
            provider=provider,
            model=model,
            worker_session_id=worker_session_id,
            status="pending",
            retry_count=retry_count,
        )
        if db is not None:
            db.add(run)
            await db.flush()
        return run

    async def add_event(
        self,
        run_id: str,
        event_type: str,
        message: str = "",
        metadata: dict | None = None,
        execution_mode: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        db: AsyncSession | None = None,
    ) -> RunEvent:
        event = RunEvent(
            run_id=run_id,
            event_type=event_type,
            message=message,
            metadata_json=json.dumps(metadata) if metadata else None,
            execution_mode=execution_mode,
            provider=provider,
            model=model,
        )
        if db is not None:
            db.add(event)
            await db.flush()
        return event

    async def update_status(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
        failure_type: str | None = None,
        db: AsyncSession | None = None,
    ) -> Run | None:
        if db is None:
            return None
        result = await db.execute(select(Run).where(Run.id == run_id))
        run = result.scalars().first()
        if run is None:
            return None
        run.status = status
        run.updated_at = datetime.now(timezone.utc)
        if error_message is not None:
            run.error_message = error_message
        if failure_type is not None:
            run.failure_type = failure_type
        await db.flush()
        return run

    async def complete_run(
        self,
        run_id: str,
        evaluator_status: str | None = None,
        db: AsyncSession | None = None,
    ) -> Run | None:
        if db is None:
            return None
        result = await db.execute(select(Run).where(Run.id == run_id))
        run = result.scalars().first()
        if run is None:
            return None

        now = datetime.now(timezone.utc)
        run.ended_at = now
        started = run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        run.duration_seconds = (now - started).total_seconds()
        run.updated_at = now

        if run.error_message:
            run.status = "failed"
        else:
            run.status = "completed"

        if evaluator_status is not None:
            run.evaluator_status = evaluator_status

        await db.flush()
        return run

    async def get_goal_progress(
        self, goal_id: str, db: AsyncSession
    ) -> GoalProgressResponse | None:
        result = await db.execute(select(Goal).where(Goal.id == goal_id))
        goal = result.scalars().first()
        if goal is None:
            return None

        result = await db.execute(
            select(Task).where(Task.goal_id == goal_id)
        )
        tasks = result.scalars().all()
        total_tasks = len(tasks)
        if total_tasks == 0:
            return GoalProgressResponse(
                goal_id=goal_id,
                total_tasks=0,
                completed_tasks=0,
                progress_percent=0.0,
                status=goal.status,
            )

        task_ids = [t.id for t in tasks]

        # Get the latest run per task in one subquery
        subq = (
            select(Run.task_id, func.max(Run.created_at).label("max_created"))
            .where(Run.task_id.in_(task_ids))
            .group_by(Run.task_id)
            .subquery()
        )
        latest_runs_q = await db.execute(
            select(Run).where(
                Run.task_id == subq.c.task_id,
                Run.created_at == subq.c.max_created,
            )
        )
        run_by_task = {r.task_id: r for r in latest_runs_q.scalars().all()}
        completed_tasks = sum(
            1 for t in tasks
            if run_by_task.get(t.id) and run_by_task[t.id].status == "completed"
        )

        progress_percent = round((completed_tasks / total_tasks) * 100, 1)

        derived_status = goal.status
        if completed_tasks == total_tasks:
            derived_status = "completed"
        elif completed_tasks > 0:
            derived_status = "active"

        return GoalProgressResponse(
            goal_id=goal_id,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            progress_percent=progress_percent,
            status=derived_status,
        )

    async def get_agent_performance(
        self, project_id: str, agent_type: str | None = None, db: AsyncSession | None = None,
    ) -> list[AgentPerformanceResponse]:
        if db is None:
            return []

        query = select(Run).where(Run.project_id == project_id)
        if agent_type:
            query = query.where(Run.agent_type == agent_type)
        result = await db.execute(query)
        runs = result.scalars().all()

        if not runs:
            return []

        grouped: dict[str, list[Run]] = {}
        for run in runs:
            grouped.setdefault(run.agent_type, []).append(run)

        responses = []
        for atype, agent_runs in grouped.items():
            total = len(agent_runs)
            completed = sum(1 for r in agent_runs if r.status == "completed")
            failed = sum(1 for r in agent_runs if r.status == "failed")
            durations = [
                r.duration_seconds for r in agent_runs if r.duration_seconds is not None
            ]
            avg_duration = sum(durations) / len(durations) if durations else 0.0
            retried = sum(1 for r in agent_runs if r.retry_count > 0)

            by_mode: dict[str, int] = {}
            by_provider: dict[str, int] = {}
            for r in agent_runs:
                by_mode[r.execution_mode] = by_mode.get(r.execution_mode, 0) + 1
                by_provider[r.provider] = by_provider.get(r.provider, 0) + 1

            responses.append(
                AgentPerformanceResponse(
                    agent_type=atype,
                    total_runs=total,
                    completed=completed,
                    failed=failed,
                    success_rate=round(completed / total, 2) if total > 0 else 0.0,
                    avg_duration_seconds=round(avg_duration, 1),
                    retry_rate=round(retried / total, 2) if total > 0 else 0.0,
                    by_execution_mode=by_mode,
                    by_provider=by_provider,
                )
            )
        return responses

    async def get_active_runs(
        self, project_id: str, db: AsyncSession
    ) -> list[Run]:
        result = await db.execute(
            select(Run)
            .where(Run.project_id == project_id, Run.status == "running")
            .order_by(Run.started_at.desc())
        )
        return list(result.scalars().all())
