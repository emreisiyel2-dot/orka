"""
Phase 4: R&D / Improvement Lab E2E Tests

Run from backend dir:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_research_lab.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import async_session, init_db
from app.models import Goal, Run, RunEvent, Task, Project, ImprovementProposal
from app.services.run_manager import RunManager
from app.services.research_analyzer import ResearchAnalyzer
from app.services.proposal_generator import ProposalGenerator
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
    mgr = RDManager()

    async with async_session() as db:
        # ═══════════════════════════════════════════
        # Setup: project with failing runs
        # ═══════════════════════════════════════════
        project = Project(name="R&D Test", description="test")
        db.add(project)
        await db.flush()
        pid = project.id

        goal = Goal(project_id=pid, title="Test Goal", status="active")
        db.add(goal)
        await db.flush()
        gid = goal.id

        # Create tasks
        task1 = Task(project_id=pid, content="Task 1", goal_id=gid)
        task2 = Task(project_id=pid, content="Task 2", goal_id=gid)
        db.add_all([task1, task2])
        await db.flush()

        run_mgr = RunManager()

        # Create 5 failed runs with same failure_type (meets threshold of 3)
        for i in range(5):
            run = await run_mgr.create_run(
                task_id=task1.id, project_id=pid, agent_type="backend",
                goal_id=gid, execution_mode="api", provider="test_api",
                model="test-v1", db=db,
            )
            await run_mgr.update_status(run.id, "running", db=db)
            await run_mgr.add_event(run.id, "started", message=f"Run {i} started", db=db)
            await run_mgr.complete_run(run.id, db=db)
            # Force to failed
            result = await db.execute(select(Run).where(Run.id == run.id))
            r = result.scalars().first()
            r.status = "failed"
            r.failure_type = "timeout"
            r.error_message = f"Execution timed out after 300s (attempt {i})"
            await db.flush()

        # Create 2 successful runs
        for i in range(2):
            run = await run_mgr.create_run(
                task_id=task2.id, project_id=pid, agent_type="frontend",
                goal_id=gid, execution_mode="simulated", db=db,
            )
            await run_mgr.update_status(run.id, "running", db=db)
            await run_mgr.complete_run(run.id, evaluator_status="passed", db=db)

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 1: ResearchAnalyzer
        # ═══════════════════════════════════════════
        print("=" * 60)
        print("TEST 1: ResearchAnalyzer")
        print("=" * 60)

        analyzer = ResearchAnalyzer()

        findings = await analyzer.analyze_project(pid, db)
        check("Analyzer returns findings", len(findings) >= 1, f"got {len(findings)}")

        failure_findings = [f for f in findings if f.finding_type == "failure_pattern"]
        check("Failure pattern detected", len(failure_findings) >= 1)

        if failure_findings:
            ff = failure_findings[0]
            check("Finding has evidence links", len(ff.related_run_ids) >= 3,
                  f"{len(ff.related_run_ids)} runs")
            check("Finding has agent type", ff.related_agent_type is not None,
                  ff.related_agent_type or "None")
            check("Finding severity from count", ff.severity in ("medium", "high", "critical"),
                  ff.severity)

        # ═══════════════════════════════════════════
        # TEST 2: ProposalGenerator
        # ═══════════════════════════════════════════
        print()
        print("=" * 60)
        print("TEST 2: ProposalGenerator")
        print("=" * 60)

        generator = ProposalGenerator()
        proposals = await generator.generate_from_analysis(
            project_id=pid, findings=findings, source_goal_id=gid, db=db,
        )
        check("Generator creates proposals", len(proposals) >= 1, f"got {len(proposals)}")

        if proposals:
            p = proposals[0]
            check("Proposal status is draft", p.status == "draft")
            check("Evidence links populated", len(p.related_run_ids) > 5,
                  f"related_run_ids={p.related_run_ids[:60]}...")
            check("Source goal linked", p.source_goal_id == gid)
            await db.commit()

        # ═══════════════════════════════════════════
        # TEST 3: RDManager - Full lifecycle
        # ═══════════════════════════════════════════
        print()
        print("=" * 60)
        print("TEST 3: Full R&D Lifecycle")
        print("=" * 60)

        # 3a: submit_to_research
        drafts = await mgr.submit_to_research(project_id=pid, goal_id=gid, db=db)
        check("submit_to_research creates drafts", len(drafts) >= 1, f"{len(drafts)} proposals")
        await db.commit()

        if not drafts:
            print("  SKIP: no drafts created")
            return

        draft_id = drafts[0].id

        # 3b: Invalid transition (draft → approved should fail)
        try:
            await mgr.approve_proposal(draft_id, guard_confirmed=True, db=db)
            check("draft→approved blocked", False, "should have raised ValueError")
        except ValueError:
            check("draft→approved blocked", True, "ValueError raised correctly")

        # 3c: submit_for_review (draft → under_review)
        proposal = await mgr.submit_for_review(draft_id, db)
        check("submit_for_review", proposal.status == "under_review")
        await db.commit()

        # 3d: approve without guard_confirmed should fail
        try:
            await mgr.approve_proposal(draft_id, guard_confirmed=False, db=db)
            check("approve without guard fails", False, "should have raised ValueError")
        except ValueError:
            check("approve without guard fails", True, "ValueError raised correctly")

        # 3e: run_approval_guard
        from app.schemas import ApprovalGuardResponse
        guard = await mgr.run_approval_guard(draft_id, db)
        check("Guard returns Assessment", isinstance(guard, ApprovalGuardResponse))
        check("Guard estimates runs", guard.estimated_runs > 0, f"{guard.estimated_runs} runs")
        check("Guard has risk_level", guard.risk_level in ("low", "medium", "high", "critical"),
              guard.risk_level)
        await db.commit()

        # 3f: approve with guard_confirmed
        proposal = await mgr.approve_proposal(
            draft_id, reviewer="test_user", notes="Approved for testing",
            guard_confirmed=True, db=db,
        )
        check("approve with guard", proposal.status == "approved")
        check("reviewer recorded", proposal.reviewed_by == "test_user")
        check("guard_approved_by set", proposal.guard_approved_by == "test_user")
        await db.commit()

        # 3g: invalid transition (approved → rejected should fail)
        try:
            await mgr.reject_proposal(draft_id, db=db)
            check("approved→rejected blocked", False, "should have raised ValueError")
        except ValueError:
            check("approved→rejected blocked", True, "ValueError raised correctly")

        # 3h: convert_to_goal
        proposal, goal_impl = await mgr.convert_to_goal(draft_id, db)
        check("convert_to_goal status", proposal.status == "converted_to_goal")
        check("implementation_goal_id set", proposal.implementation_goal_id is not None)
        check("Goal type=improvement", goal_impl.type == "improvement")
        check("Goal source_goal_id", goal_impl.source_goal_id == gid)
        check("Goal title prefixed", goal_impl.title.startswith("[Improvement]"))
        await db.commit()

        # 3i: converted_to_goal is terminal
        try:
            await mgr.archive_proposal(draft_id, db)
            check("terminal state blocked", False, "should have raised ValueError")
        except ValueError:
            check("terminal state blocked", True, "ValueError raised correctly")

        # ═══════════════════════════════════════════
        # TEST 4: Reject & Archive
        # ═══════════════════════════════════════════
        print()
        print("=" * 60)
        print("TEST 4: Reject & Archive Flows")
        print("=" * 60)

        # Create another proposal to test reject
        draft2 = ImprovementProposal(
            project_id=pid, title="Test reject flow",
            status="draft", analysis_type="manual",
        )
        db.add(draft2)
        await db.flush()

        await mgr.submit_for_review(draft2.id, db)
        rejected = await mgr.reject_proposal(draft2.id, reason="Not needed", db=db)
        check("Reject flow", rejected.status == "rejected")
        check("Reject notes", rejected.review_notes == "Not needed")

        # Archive rejected
        archived = await mgr.archive_proposal(draft2.id, db)
        check("Archive rejected", archived.status == "archived")

        # Archive draft directly
        draft3 = ImprovementProposal(
            project_id=pid, title="Archive draft",
            status="draft", analysis_type="manual",
        )
        db.add(draft3)
        await db.flush()
        archived_draft = await mgr.archive_proposal(draft3.id, db)
        check("Archive draft", archived_draft.status == "archived")

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 5: get_project_proposals
        # ═══════════════════════════════════════════
        print()
        print("=" * 60)
        print("TEST 5: Proposal Queries")
        print("=" * 60)

        all_proposals = await mgr.get_project_proposals(pid, db=db)
        check("List all proposals", len(all_proposals) >= 3, f"got {len(all_proposals)}")

        converted = await mgr.get_project_proposals(pid, status="converted_to_goal", db=db)
        check("Filter by status", len(converted) >= 1, f"got {len(converted)}")

        # ═══════════════════════════════════════════
        # TEST 6: Evidence traceability
        # ═══════════════════════════════════════════
        print()
        print("=" * 60)
        print("TEST 6: Evidence Traceability")
        print("=" * 60)

        import json
        converted_proposal = converted[0]
        run_ids = json.loads(converted_proposal.related_run_ids)
        goal_ids = json.loads(converted_proposal.related_goal_ids)
        task_ids = json.loads(converted_proposal.related_task_ids)
        check("Evidence: run IDs present", len(run_ids) >= 3, f"{len(run_ids)} runs")
        check("Evidence: goal IDs present", gid in goal_ids, f"goals={goal_ids}")
        check("Evidence: task IDs present", len(task_ids) >= 1, f"tasks={task_ids}")
        check("Evidence: agent type", converted_proposal.related_agent_type is not None,
              converted_proposal.related_agent_type)

        # ═══════════════════════════════════════════
        # TEST 7: Goal-source traceability
        # ═══════════════════════════════════════════
        print()
        print("=" * 60)
        print("TEST 7: Goal Traceability")
        print("=" * 60)

        impl_goal = goal_impl
        check("Goal.type=improvement", impl_goal.type == "improvement")
        check("Goal.source=research", impl_goal.source == "research")
        check("Goal.source_goal_id→original", impl_goal.source_goal_id == gid,
              f"{impl_goal.source_goal_id} → {gid}")

        await db.commit()

    # ═══════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════
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
