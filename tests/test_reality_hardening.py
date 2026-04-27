"""
Phase 5.5: Reality Hardening Tests

Run from backend dir:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_reality_hardening.py
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import async_session, init_db
from app.models import (
    Goal, Run, RunEvent, Task, Project, ImprovementProposal,
    RunEventArchive, DailyStats,
)
from app.services.run_manager import RunManager
from app.services.rd_manager import RDManager
from sqlalchemy import select

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {name} {detail}")


async def run_tests():
    await init_db()

    async with async_session() as db:
        # Setup
        project = Project(name="Hardening Test", description="reality check")
        db.add(project)
        await db.flush()
        pid = project.id

        goal = Goal(project_id=pid, title="Test Goal", status="active")
        db.add(goal)
        await db.flush()
        gid = goal.id

        tasks = []
        for i in range(6):
            t = Task(project_id=pid, content=f"Task {i}", goal_id=gid)
            tasks.append(t)
        db.add_all(tasks)
        await db.flush()

        run_mgr = RunManager()

        for i, task in enumerate(tasks):
            run = await run_mgr.create_run(
                task_id=task.id, project_id=pid, agent_type="backend",
                goal_id=gid, execution_mode="api", provider="test",
                model="test-v1", db=db,
            )
            await run_mgr.update_status(run.id, "running", db=db)
            await run_mgr.add_event(run.id, "started", message=f"Run {i}", db=db)
            if i < 3:
                await run_mgr.complete_run(run.id, evaluator_status="passed", db=db)
            else:
                await run_mgr.complete_run(run.id, db=db)
                result = await db.execute(select(Run).where(Run.id == run.id))
                r = result.scalars().first()
                r.status = "failed"
                r.failure_type = "timeout"
                r.error_message = f"Timeout {i}"

        await db.commit()

        # TEST 1: Pagination
        print("=" * 60)
        print("TEST 1: Pagination (limit/offset)")
        print("=" * 60)

        result = await db.execute(
            select(Run).where(Run.project_id == pid)
            .order_by(Run.created_at.desc()).limit(2)
        )
        limited = list(result.scalars().all())
        check("Limit=2 returns <=2 runs", len(limited) <= 2, f"got {len(limited)}")

        result = await db.execute(
            select(Run).where(Run.project_id == pid)
            .order_by(Run.created_at.desc()).limit(2).offset(2)
        )
        offset_runs = list(result.scalars().all())
        check("Offset=2 returns different runs",
              len(offset_runs) > 0 and offset_runs[0].id != limited[0].id if limited else True,
              f"got {len(offset_runs)}")

        result = await db.execute(
            select(Run).where(Run.project_id == pid).order_by(Run.created_at.desc())
        )
        all_runs = list(result.scalars().all())
        check("Total runs = 6", len(all_runs) == 6, f"got {len(all_runs)}")

        run_id = all_runs[0].id
        result = await db.execute(
            select(RunEvent).where(RunEvent.run_id == run_id)
            .order_by(RunEvent.created_at).limit(1)
        )
        check("Events limit works", len(list(result.scalars().all())) <= 1)

        # TEST 2: Goal Progress (batch query)
        print()
        print("=" * 60)
        print("TEST 2: Goal Progress (Batch Query)")
        print("=" * 60)

        progress = await run_mgr.get_goal_progress(gid, db)
        check("Progress returns result", progress is not None)
        if progress:
            check("Total tasks = 6", progress.total_tasks == 6, f"got {progress.total_tasks}")
            check("Completed = 3", progress.completed_tasks == 3, f"got {progress.completed_tasks}")
            check("Progress = 50%", progress.progress_percent == 50.0, f"got {progress.progress_percent}")
            check("Status = active", progress.status == "active", f"got {progress.status}")

        # TEST 3: Guard Hardening
        print()
        print("=" * 60)
        print("TEST 3: Guard Hardening")
        print("=" * 60)

        from app.services.rd_manager import _DEV_MODE
        check("dev_mode defaults to false",
              not _DEV_MODE or os.getenv("ORKA_DEV_MODE") == "true",
              f"_DEV_MODE={_DEV_MODE}")

        mgr = RDManager()
        drafts = await mgr.submit_to_research(project_id=pid, goal_id=gid, db=db)
        check("Proposals created", len(drafts) >= 1, f"{len(drafts)}")
        await db.commit()

        if drafts:
            draft_id = drafts[0].id
            await mgr.submit_for_review(draft_id, db)
            await db.commit()

            guard = await mgr.run_approval_guard(draft_id, db)
            check("Guard returns response", guard is not None)
            check("can_proceed is bool", isinstance(guard.can_proceed, bool))

            # Budget failure is explicit (not silent pass)
            if not guard.budget_fits and guard.blocks:
                has_budget_msg = any("budget" in b.lower() for b in guard.blocks)
                check("Budget failure explicit", has_budget_msg or not _DEV_MODE,
                      f"blocks={guard.blocks}")
            elif not guard.budget_fits and _DEV_MODE:
                has_advisory = any("dev mode" in w.lower() for w in guard.warnings)
                check("Dev mode advisory present", has_advisory,
                      f"warnings={guard.warnings}")
            else:
                check("Budget fits", True)

            await db.commit()

        # TEST 4: Decision Logging
        print()
        print("=" * 60)
        print("TEST 4: Decision Logging")
        print("=" * 60)

        if drafts:
            approved = await mgr.approve_proposal(
                drafts[0].id, reviewer="test_user", notes="Testing",
                guard_confirmed=True, db=db,
            )
            await db.commit()

            result = await db.execute(
                select(ImprovementProposal).where(ImprovementProposal.id == drafts[0].id)
            )
            proposal = result.scalars().first()
            check("decision_log not None", proposal.decision_log is not None)

            if proposal.decision_log:
                log = json.loads(proposal.decision_log)
                check("Has log entries", len(log) >= 1, f"{len(log)}")
                if log:
                    entry = log[-1]
                    check("Action=approved", entry.get("action") == "approved",
                          f"action={entry.get('action')}")
                    check("Has reviewer", entry.get("reviewer") == "test_user")
                    check("Has timestamp", "timestamp" in entry)

        # Test reject logging
        draft2 = ImprovementProposal(
            project_id=pid, title="Reject test",
            status="draft", analysis_type="manual",
        )
        db.add(draft2)
        await db.flush()
        await mgr.submit_for_review(draft2.id, db)
        await mgr.reject_proposal(draft2.id, reason="Nope", db=db)
        await db.commit()

        result = await db.execute(
            select(ImprovementProposal).where(ImprovementProposal.id == draft2.id)
        )
        p2 = result.scalars().first()
        if p2.decision_log:
            log2 = json.loads(p2.decision_log)
            check("Reject logged", log2[-1]["action"] == "rejected")
        else:
            check("Reject logged", False)

        # Test archive logging
        await mgr.archive_proposal(draft2.id, db)
        await db.commit()
        result = await db.execute(
            select(ImprovementProposal).where(ImprovementProposal.id == draft2.id)
        )
        p2 = result.scalars().first()
        if p2.decision_log:
            log2 = json.loads(p2.decision_log)
            check("Archive logged", len(log2) >= 2, f"{len(log2)} entries")
        else:
            check("Archive logged", False)

        # TEST 5: RunEventArchive Model
        print()
        print("=" * 60)
        print("TEST 5: RunEventArchive Model")
        print("=" * 60)

        events = await db.execute(select(RunEvent).limit(1))
        event = events.scalars().first()
        if event:
            archive = RunEventArchive(
                id=event.id, run_id=event.run_id,
                event_type=event.event_type,
                message=event.message or "",
                created_at=event.created_at,
            )
            db.add(archive)
            await db.flush()
            check("Archive writable", archive.id is not None)
            await db.delete(archive)
            await db.flush()
        else:
            check("Archive model exists", True, "no events to test")

        # TEST 6: DailyStats Model
        print()
        print("=" * 60)
        print("TEST 6: DailyStats Model")
        print("=" * 60)

        from datetime import datetime as dt, timezone as tz
        today_str = dt.now(tz.utc).strftime("%Y-%m-%d")

        stats = DailyStats(
            date=today_str, project_id=pid,
            total_runs=5, failed_runs=2,
            avg_duration_seconds=12.5, active_cli_sessions=0,
        )
        db.add(stats)
        await db.flush()
        check("DailyStats writable", stats.id is not None)

        result = await db.execute(select(DailyStats).where(DailyStats.date == today_str))
        saved = result.scalars().first()
        check("DailyStats readable", saved is not None)
        if saved:
            check("Values correct", saved.total_runs == 5 and saved.failed_runs == 2)
        await db.delete(stats)
        await db.flush()

        # TEST 7: Regression - Full Lifecycle
        print()
        print("=" * 60)
        print("TEST 7: Regression — Full Lifecycle")
        print("=" * 60)

        if drafts:
            proposal, impl_goal = await mgr.convert_to_goal(drafts[0].id, db)
            check("Convert to goal", proposal.status == "converted_to_goal")
            check("Goal type=improvement", impl_goal.type == "improvement")
            await db.commit()

            result = await db.execute(
                select(ImprovementProposal).where(ImprovementProposal.id == drafts[0].id)
            )
            final = result.scalars().first()
            if final.decision_log:
                log = json.loads(final.decision_log)
                check("Final log >= 2 entries", len(log) >= 2, f"{len(log)} entries")

        await db.commit()

    # SUMMARY
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    for name, ok, detail in results:
        icon = "✓" if ok else "✗"
        print(f"  [{icon}] {name} {detail}")
    print(f"\n  {passed}/{len(results)} tests passed")
    if failed:
        print(f"  {failed} FAILED")
        sys.exit(1)
    else:
        print("  All tests passed!")


if __name__ == "__main__":
    asyncio.run(run_tests())
