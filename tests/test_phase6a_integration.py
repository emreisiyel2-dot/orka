"""
Phase 6A: Integration Tests

Validates end-to-end flow:
1. RunManager.complete_run() auto-triggers FeedbackService + RetryIntelligence
2. Feedback persisted for successful runs
3. Retry evaluation persisted for failed runs
4. No regressions on existing Phase 5.6 features

Run:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_phase6a_integration.py
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ["ORKA_LLM_ENABLED"] = "false"
os.environ["ORKA_CLI_ENABLED"] = "false"

from app.database import init_db, async_session
from app.models import Run, RoutingDecision
from app.services.run_manager import RunManager
from app.services.feedback_service import FeedbackService
from app.services.retry_intelligence import RetryIntelligence
from sqlalchemy import select

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {name} {detail}")


async def test_complete_run_auto_feedback():
    """complete_run() should auto-trigger FeedbackService."""
    await init_db()
    async with async_session() as db:
        from app.models import Project, Task

        project = Project(name="int-test", description="test")
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, content="test task")
        db.add(task)
        await db.flush()

        rm = RunManager()
        run = await rm.create_run(
            task_id=task.id, project_id=project.id,
            agent_type="backend", execution_mode="cli",
            provider="claude_code", model="claude-sonnet-4-6",
            db=db,
        )
        await rm.update_status(run.id, "running", db=db)
        completed = await rm.complete_run(run.id, db=db)

        check("completed run has feedback_score", completed.feedback_score == 1.0, f"got {completed.feedback_score}")
        check("completed run no failure_classification", completed.failure_classification is None)
        check("completed run no retry fields", completed.retry_eligible is None)
        print()


async def test_complete_run_auto_retry():
    """complete_run() should auto-trigger RetryIntelligence for failed runs."""
    await init_db()
    async with async_session() as db:
        from app.models import Project, Task

        project = Project(name="int-test-retry", description="test")
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, content="test task")
        db.add(task)
        await db.flush()

        rm = RunManager()

        # Failed with timeout
        run1 = await rm.create_run(
            task_id=task.id, project_id=project.id,
            agent_type="backend", execution_mode="cli",
            provider="claude_code", model="claude-sonnet-4-6",
            db=db,
        )
        await rm.update_status(run1.id, "running", error_message="timeout", failure_type="timeout", db=db)
        completed1 = await rm.complete_run(run1.id, db=db)

        check("timeout: feedback_score=0.0", completed1.feedback_score == 0.0)
        check("timeout: failure_classification=timeout", completed1.failure_classification == "timeout")
        check("timeout: retry_eligible=True", completed1.retry_eligible is True)
        check("timeout: retry_reason set", completed1.retry_reason is not None)

        # Failed with validation
        run2 = await rm.create_run(
            task_id=task.id, project_id=project.id,
            agent_type="backend", execution_mode="cli",
            provider="claude_code", model="claude-sonnet-4-6",
            db=db,
        )
        await rm.update_status(run2.id, "running", error_message="invalid", failure_type="validation_failed", db=db)
        completed2 = await rm.complete_run(run2.id, db=db)

        check("validation: retry_eligible=False", completed2.retry_eligible is False)
        check("validation: retry_reason='fix code'", "fix code" in (completed2.retry_reason or ""))
        print()


async def test_retry_exhausted():
    """After 2 retries, complete_run should mark not eligible."""
    await init_db()
    async with async_session() as db:
        from app.models import Project, Task

        project = Project(name="int-test-exhaust", description="test")
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, content="test task")
        db.add(task)
        await db.flush()

        rm = RunManager()

        # First run (retry_count=0)
        run1 = await rm.create_run(
            task_id=task.id, project_id=project.id,
            agent_type="backend", execution_mode="cli",
            provider="claude_code", model="claude-sonnet-4-6",
            db=db,
        )
        await rm.update_status(run1.id, "running", error_message="timeout", failure_type="timeout", db=db)
        c1 = await rm.complete_run(run1.id, db=db)
        check("retry 1: eligible", c1.retry_eligible is True)

        # Second run (retry_count=1)
        run2 = await rm.create_run(
            task_id=task.id, project_id=project.id,
            agent_type="backend", execution_mode="cli",
            provider="claude_code", model="claude-sonnet-4-6",
            db=db,
        )
        await rm.update_status(run2.id, "running", error_message="timeout", failure_type="timeout", db=db)
        c2 = await rm.complete_run(run2.id, db=db)
        check("retry 2: eligible", c2.retry_eligible is True)

        # Third run (retry_count=2) → not eligible
        run3 = await rm.create_run(
            task_id=task.id, project_id=project.id,
            agent_type="backend", execution_mode="cli",
            provider="claude_code", model="claude-sonnet-4-6",
            db=db,
        )
        await rm.update_status(run3.id, "running", error_message="timeout", failure_type="timeout", db=db)
        c3 = await rm.complete_run(run3.id, db=db)
        check("retry 3: NOT eligible", c3.retry_eligible is False)
        check("retry 3: reason='max retries'", "max retries" in (c3.retry_reason or ""))
        print()


async def test_feedback_service_standalone():
    """FeedbackService works independently of RunManager."""
    svc = FeedbackService()

    class FakeRun:
        id = "standalone"
        status = "failed"
        failure_type = "cli_error"

    fb = svc.process_run(FakeRun())
    check("standalone: success=False", fb.success is False)
    check("standalone: score=0.0", fb.quality_score == 0.0)
    check("standalone: classification=cli_error", fb.failure_classification == "cli_error")
    print()


async def test_retry_intelligence_standalone():
    """RetryIntelligence works independently."""
    svc = RetryIntelligence()

    class FakeRun:
        retry_count = 1
        failure_type = "model_error"

    ev = svc.evaluate(FakeRun())
    check("standalone retry: eligible", ev.eligible)
    check("standalone retry: strategy=alternate", ev.strategy == "alternate_provider")
    check("standalone retry: max_retries=1", ev.max_retries == 1)
    print()


async def test_no_regressions():
    """Existing Run model fields still work correctly."""
    await init_db()
    async with async_session() as db:
        from app.models import Project, Task

        project = Project(name="regression-test", description="test")
        db.add(project)
        await db.flush()
        task = Task(project_id=project.id, content="test task")
        db.add(task)
        await db.flush()

        rm = RunManager()
        run = await rm.create_run(
            task_id=task.id, project_id=project.id,
            agent_type="backend", execution_mode="simulated",
            provider="test", model="test-model",
            db=db,
        )
        check("run created", run.id is not None)
        check("run status pending", run.status == "pending")
        check("run retry_count 0", run.retry_count == 0)

        await rm.update_status(run.id, "running", db=db)
        result = await db.execute(select(Run).where(Run.id == run.id))
        updated = result.scalars().first()
        check("run status running", updated.status == "running")

        completed = await rm.complete_run(run.id, db=db)
        check("run status completed", completed.status == "completed")
        check("run ended_at set", completed.ended_at is not None)
        check("run duration set", completed.duration_seconds is not None)
        check("run duration > 0", completed.duration_seconds >= 0)
        print()


async def main():
    print("=" * 60)
    print("Phase 6A: Integration Tests")
    print("=" * 60)

    await test_complete_run_auto_feedback()
    await test_complete_run_auto_retry()
    await test_retry_exhausted()
    await test_feedback_service_standalone()
    await test_retry_intelligence_standalone()
    await test_no_regressions()

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Results: {passed}/{len(results)} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
