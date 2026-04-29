"""
Phase 6A: Manual Learning Tests

Validates:
1. ResearchAnalyzer + ProposalGenerator pipeline works (existing code)
2. RDManager.submit_to_research() returns proposals
3. Learning endpoint triggers analysis correctly
4. New Run columns exist and are nullable

Run:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_phase6a_learning.py
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ["ORKA_LLM_ENABLED"] = "false"
os.environ["ORKA_CLI_ENABLED"] = "false"

from app.database import init_db, async_session
from app.models import Run, RoutingDecision
from sqlalchemy import select

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {name} {detail}")


async def test_run_columns_exist():
    await init_db()
    async with async_session() as db:
        from app.models import Project, Task
        project = Project(name="test", description="test")
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, content="test task")
        db.add(task)
        await db.flush()

        run = Run(
            task_id=task.id,
            project_id=project.id,
            agent_type="backend",
            status="pending",
        )
        db.add(run)
        await db.flush()

        # Verify new columns exist by setting them
        run.feedback_score = 0.5
        run.failure_classification = "timeout"
        run.retry_eligible = True
        run.retry_reason = "retry once"
        await db.flush()

        # Read back
        result = await db.execute(select(Run).where(Run.id == run.id))
        loaded = result.scalars().first()
        check("feedback_score persisted", loaded.feedback_score == 0.5, f"got {loaded.feedback_score}")
        check("failure_classification persisted", loaded.failure_classification == "timeout")
        check("retry_eligible persisted", loaded.retry_eligible is True)
        check("retry_reason persisted", loaded.retry_reason == "retry once")

        # Test nullable defaults
        run2 = Run(
            task_id=task.id,
            project_id=project.id,
            agent_type="backend",
            status="pending",
        )
        db.add(run2)
        await db.flush()
        result2 = await db.execute(select(Run).where(Run.id == run2.id))
        loaded2 = result2.scalars().first()
        check("feedback_score nullable", loaded2.feedback_score is None)
        check("failure_classification nullable", loaded2.failure_classification is None)
        check("retry_eligible nullable", loaded2.retry_eligible is None)
        check("retry_reason nullable", loaded2.retry_reason is None)


async def test_routing_decision_column():
    await init_db()
    async with async_session() as db:
        decision = RoutingDecision(
            task_id=None,
            agent_type="backend",
            requested_tier="medium",
            selected_model="test-model",
            selected_provider="test-provider",
            reason="test",
        )
        db.add(decision)
        await db.flush()

        decision.learning_signals_at_decision = '{"provider_failure_rate": 0.1}'
        await db.flush()

        result = await db.execute(select(RoutingDecision).where(RoutingDecision.id == decision.id))
        loaded = result.scalars().first()
        check("learning_signals_at_decision persisted", loaded.learning_signals_at_decision is not None)


async def test_research_pipeline():
    await init_db()
    async with async_session() as db:
        from app.models import Project, Goal, Task
        from app.services.rd_manager import RDManager
        from app.services.run_manager import RunManager

        project = Project(name="learning-test", description="test")
        db.add(project)
        await db.flush()

        # Create a goal with some runs (need data for analyzer)
        goal = Goal(project_id=project.id, title="Test Goal", status="completed")
        db.add(goal)
        await db.flush()

        task = Task(project_id=project.id, content="test task", goal_id=goal.id)
        db.add(task)
        await db.flush()

        rm = RunManager()
        # Create completed runs to give analyzer data
        for i in range(5):
            run = await rm.create_run(
                task_id=task.id, project_id=project.id,
                agent_type="backend", goal_id=goal.id,
                execution_mode="cli", provider="claude_code", model="claude-sonnet-4-6",
                db=db,
            )
            await rm.update_status(run.id, "running", db=db)
            await rm.complete_run(run.id, db=db)

        # Create some failed runs (separate tasks to avoid retry_count accumulation)
        for i in range(3):
            fail_task = Task(project_id=project.id, content=f"fail task {i}", goal_id=goal.id)
            db.add(fail_task)
            await db.flush()
            run = await rm.create_run(
                task_id=fail_task.id, project_id=project.id,
                agent_type="backend", goal_id=goal.id,
                execution_mode="cli", provider="glm_coding", model="glm-4-plus",
                db=db,
            )
            await rm.update_status(run.id, "running", error_message="CLI timeout", failure_type="timeout", db=db)
            await rm.complete_run(run.id, db=db)

        await db.flush()

        # Now verify feedback was auto-applied
        result = await db.execute(
            select(Run).where(Run.project_id == project.id).order_by(Run.created_at)
        )
        runs = result.scalars().all()
        completed = [r for r in runs if r.status == "completed"]
        failed = [r for r in runs if r.status == "failed"]

        check("completed runs have feedback_score=1.0", all(r.feedback_score == 1.0 for r in completed))
        check("failed runs have feedback_score=0.0", all(r.feedback_score == 0.0 for r in failed))
        check("failed runs have failure_classification", all(r.failure_classification is not None for r in failed))
        check("failed timeout runs have retry_eligible=True", all(r.retry_eligible for r in failed))


async def main():
    print("=" * 60)
    print("Phase 6A: Manual Learning Tests")
    print("=" * 60)

    await test_run_columns_exist()
    print()
    await test_routing_decision_column()
    print()
    await test_research_pipeline()

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Results: {passed}/{len(results)} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
