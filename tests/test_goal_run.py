"""
Phase 3C: Goal/Run Management E2E Tests

Run from backend dir:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_goal_run.py
"""
import asyncio
import sys
import os

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import async_session, init_db
from app.models import Goal, Run, RunEvent, Task, Project
from app.services.run_manager import RunManager
from sqlalchemy import select

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


async def run_tests():
    await init_db()

    run_mgr = RunManager()

    async with async_session() as db:
        # ── Test 1: Goal CRUD ──────────────────────────
        print("=" * 60)
        print("TEST 1: Goal CRUD")
        print("=" * 60)

        project = Project(name="Test Project", description="Goal/Run test")
        db.add(project)
        await db.flush()
        pid = project.id

        goal = Goal(
            project_id=pid,
            title="Test Goal",
            description="A test goal",
            status="planned",
        )
        db.add(goal)
        await db.flush()
        goal_id = goal.id

        result = await db.execute(select(Goal).where(Goal.id == goal_id))
        fetched = result.scalars().first()
        ok = fetched is not None and fetched.title == "Test Goal" and fetched.status == "planned"
        print(f"  [{'OK' if ok else 'FAIL':4s}] Create + fetch goal")
        if not ok:
            results.append(("Goal CRUD", FAIL, "create/fetch"))
            return
        results.append(("Goal CRUD", PASS, "create/fetch"))

        fetched.status = "active"
        fetched.title = "Updated Goal"
        await db.flush()
        result = await db.execute(select(Goal).where(Goal.id == goal_id))
        updated = result.scalars().first()
        ok = updated.title == "Updated Goal" and updated.status == "active"
        print(f"  [{'OK' if ok else 'FAIL':4s}] Update goal")
        results.append(("Goal update", PASS if ok else FAIL, "status+title"))

        # ── Test 2: Run Lifecycle ──────────────────────
        print("=" * 60)
        print("TEST 2: Run Lifecycle")
        print("=" * 60)

        task = Task(project_id=pid, content="Test task for run", goal_id=goal_id)
        db.add(task)
        await db.flush()
        task_id = task.id

        run = await run_mgr.create_run(
            task_id=task_id,
            project_id=pid,
            agent_type="backend",
            goal_id=goal_id,
            execution_mode="simulated",
            provider="test",
            model="test-model",
            db=db,
        )
        ok = run is not None and run.status == "pending" and run.retry_count == 0
        print(f"  [{'OK' if ok else 'FAIL':4s}] Create run (pending)")
        results.append(("Run create", PASS if ok else FAIL, "pending state"))

        await run_mgr.update_status(run.id, "running", db=db)
        result = await db.execute(select(Run).where(Run.id == run.id))
        r = result.scalars().first()
        ok = r.status == "running"
        print(f"  [{'OK' if ok else 'FAIL':4s}] Update run → running")
        results.append(("Run status", PASS if ok else FAIL, "running"))

        await run_mgr.complete_run(run.id, evaluator_status="passed", db=db)
        result = await db.execute(select(Run).where(Run.id == run.id))
        r = result.scalars().first()
        ok = r.status == "completed" and r.duration_seconds is not None and r.evaluator_status == "passed"
        print(f"  [{'OK' if ok else 'FAIL':4s}] Complete run (duration={r.duration_seconds:.2f}s)")
        results.append(("Run complete", PASS if ok else FAIL, f"duration={r.duration_seconds:.2f}s"))

        # ── Test 3: RunEvent Timeline ──────────────────
        print("=" * 60)
        print("TEST 3: RunEvent Timeline")
        print("=" * 60)

        await run_mgr.add_event(
            run.id, "started",
            message="Run started",
            execution_mode="simulated",
            provider="test",
            db=db,
        )
        await run_mgr.add_event(
            run.id, "completed",
            message="Run completed",
            db=db,
        )

        result = await db.execute(
            select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.created_at)
        )
        events = list(result.scalars().all())
        ok = len(events) == 2 and events[0].event_type == "started" and events[1].event_type == "completed"
        print(f"  [{'OK' if ok else 'FAIL':4s}] 2 events in order: {[e.event_type for e in events]}")
        results.append(("RunEvent timeline", PASS if ok else FAIL, f"{len(events)} events"))

        # ── Test 4: Goal Progress ──────────────────────
        print("=" * 60)
        print("TEST 4: Goal Progress")
        print("=" * 60)

        progress = await run_mgr.get_goal_progress(goal_id, db)
        ok = progress is not None and progress.total_tasks == 1 and progress.completed_tasks == 1 and progress.progress_percent == 100.0
        print(f"  [{'OK' if ok else 'FAIL':4s}] Progress: {progress.completed_tasks}/{progress.total_tasks} = {progress.progress_percent}%")
        results.append(("Goal progress", PASS if ok else FAIL, f"{progress.progress_percent}%"))

        # Add another task without completed run
        task2 = Task(project_id=pid, content="Pending task", goal_id=goal_id)
        db.add(task2)
        await db.flush()

        run2 = await run_mgr.create_run(
            task_id=task2.id, project_id=pid, agent_type="frontend",
            goal_id=goal_id, db=db,
        )
        await run_mgr.update_status(run2.id, "running", db=db)

        progress2 = await run_mgr.get_goal_progress(goal_id, db)
        ok = progress2.total_tasks == 2 and progress2.completed_tasks == 1 and progress2.progress_percent == 50.0
        print(f"  [{'OK' if ok else 'FAIL':4s}] Partial progress: {progress2.completed_tasks}/{progress2.total_tasks} = {progress2.progress_percent}%")
        results.append(("Goal partial progress", PASS if ok else FAIL, f"{progress2.progress_percent}%"))

        # ── Test 5: Retry Semantics ────────────────────
        print("=" * 60)
        print("TEST 5: Retry Semantics")
        print("=" * 60)

        run_fail = await run_mgr.create_run(
            task_id=task2.id, project_id=pid, agent_type="frontend",
            goal_id=goal_id, db=db,
        )
        await run_mgr.update_status(run_fail.id, "running", db=db)
        await run_mgr.complete_run(run_fail.id, db=db)
        result = await db.execute(select(Run).where(Run.id == run_fail.id))
        rf = result.scalars().first()
        rf.status = "failed"
        rf.error_message = "test failure"
        await db.flush()

        run_retry = await run_mgr.create_run(
            task_id=task2.id, project_id=pid, agent_type="frontend",
            goal_id=goal_id, db=db,
        )
        ok = run_retry.retry_count == 2  # 2 previous runs on this task
        print(f"  [{'OK' if ok else 'FAIL':4s}] Retry count = {run_retry.retry_count} (2 previous runs)")
        results.append(("Retry semantics", PASS if ok else FAIL, f"retry_count={run_retry.retry_count}"))

        # ── Test 6: Agent Performance ──────────────────
        print("=" * 60)
        print("TEST 6: Agent Performance")
        print("=" * 60)

        perf = await run_mgr.get_agent_performance(pid, db=db)
        ok = len(perf) >= 1
        print(f"  [{'OK' if ok else 'FAIL':4s}] Got performance for {len(perf)} agent types")
        if ok:
            for p in perf:
                print(f"         {p.agent_type}: {p.total_runs} runs, {p.success_rate:.0%} success, avg {p.avg_duration_seconds:.1f}s")
        results.append(("Agent performance", PASS if ok else FAIL, f"{len(perf)} agent types"))

        await db.commit()

    # ── Summary ────────────────────────────────────
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, s, _ in results if s == PASS)
    total = len(results)
    for name, status, detail in results:
        icon = "✓" if status == PASS else "✗"
        print(f"  [{icon}] {name}: {detail}")
    print(f"\n  {passed}/{total} tests passed")
    if passed == total:
        print("\n  All tests passed!")
    else:
        print(f"\n  {total - passed} test(s) FAILED")


if __name__ == "__main__":
    asyncio.run(run_tests())
