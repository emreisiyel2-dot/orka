"""
Phase 6A: Real-World Validation — End-to-End Feedback / Retry / Learning Tests

Validates the full lifecycle:
  1. Successful task → feedback_score=1.0, no failure_classification
  2. Failed task (timeout) → feedback_score=0.0, classification=timeout, retry_eligible=True
  3. Failed task (cli_error) → feedback_score=0.0, classification=cli_error, retry_eligible=True
  4. Failed task (validation_failed) → feedback_score=0.0, classification=validation_failed, retry_eligible=False
  5. POST /api/feedback/run/{run_id} → reprocesses feedback, persists to DB
  6. POST /api/retry/evaluate/{run_id} → evaluates retry, persists to DB
  7. POST /api/learning/analyze → triggers research, creates proposals via RDManager

Run:
    cd backend && rm -f orka.db && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_phase6a_real_validation.py
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ["ORKA_LLM_ENABLED"] = "false"
os.environ["ORKA_CLI_ENABLED"] = "false"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
os.chdir(PROJECT_ROOT / "backend")

from app.database import init_db, async_session
from app.models import Project, Task, Goal, Run, ImprovementProposal
from app.services.feedback_service import FeedbackService
from app.services.retry_intelligence import RetryIntelligence
from app.services.run_manager import RunManager
from sqlalchemy import select

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    status = "OK  " if ok else "FAIL"
    print(f"  [{status}] {name} {detail}")


async def seed_project() -> tuple[str, str]:
    """Create a project + goal, return (project_id, goal_id)."""
    async with async_session() as db:
        project = Project(name="validation-test", description="Phase 6A E2E")
        db.add(project)
        await db.flush()

        goal = Goal(project_id=project.id, title="Validation Goal", status="active")
        db.add(goal)
        await db.flush()

        await db.commit()
        return project.id, goal.id


async def make_task(project_id: str, goal_id: str, label: str = "task") -> str:
    """Create a fresh task (avoids retry_count accumulation). Returns task_id."""
    async with async_session() as db:
        task = Task(project_id=project_id, content=f"{label} task", goal_id=goal_id)
        db.add(task)
        await db.flush()
        tid = task.id
        await db.commit()
        return tid


async def create_and_complete_run(
    task_id: str, project_id: str, goal_id: str,
    error_message: str | None = None,
    failure_type: str | None = None,
    agent_type: str = "backend",
    provider: str = "claude_code",
    model: str = "claude-sonnet-4-6",
) -> Run:
    """Full lifecycle: create → running → complete (with optional failure)."""
    rm = RunManager()
    async with async_session() as db:
        run = await rm.create_run(
            task_id=task_id, project_id=project_id,
            agent_type=agent_type, goal_id=goal_id,
            execution_mode="cli", provider=provider, model=model,
            db=db,
        )
        run_id = run.id
        await db.commit()

    async with async_session() as db:
        await rm.update_status(
            run_id, "running",
            error_message=error_message,
            failure_type=failure_type,
            db=db,
        )
        await db.commit()

    async with async_session() as db:
        run = await rm.complete_run(run_id, db=db)
        await db.commit()

    # Re-read to verify persistence
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        return result.scalars().first()


# ────────────────────────────────────────────────────────────────────
# Test 1: Successful task
# ────────────────────────────────────────────────────────────────────

async def test_successful_task(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 1: Successful task")
    print("─" * 60)

    task_id = await make_task(project_id, goal_id, "success")
    run = await create_and_complete_run(task_id, project_id, goal_id)

    check("status is completed", run.status == "completed", f"got {run.status}")
    check("feedback_score is 1.0", run.feedback_score == 1.0, f"got {run.feedback_score}")
    check("failure_classification is None", run.failure_classification is None, f"got {run.failure_classification}")
    check("retry_eligible is None (not evaluated for success)", run.retry_eligible is None, f"got {run.retry_eligible}")
    check("retry_reason is None", run.retry_reason is None, f"got {run.retry_reason}")
    check("error_message is None", run.error_message is None, f"got {run.error_message}")


# ────────────────────────────────────────────────────────────────────
# Test 2: Failed task — timeout
# ────────────────────────────────────────────────────────────────────

async def test_failed_timeout(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 2: Failed task (timeout)")
    print("─" * 60)

    task_id = await make_task(project_id, goal_id, "timeout-fail")
    run = await create_and_complete_run(
        task_id, project_id, goal_id,
        error_message="Process timed out after 300s",
        failure_type="timeout",
    )

    check("status is failed", run.status == "failed", f"got {run.status}")
    check("feedback_score is 0.0", run.feedback_score == 0.0, f"got {run.feedback_score}")
    check("failure_classification is 'timeout'", run.failure_classification == "timeout", f"got {run.failure_classification}")
    check("retry_eligible is True", run.retry_eligible is True, f"got {run.retry_eligible}")
    check("retry_reason contains 'timeout'", "timeout" in (run.retry_reason or ""), f"got {run.retry_reason}")


# ────────────────────────────────────────────────────────────────────
# Test 3: Failed task — cli_error
# ────────────────────────────────────────────────────────────────────

async def test_failed_cli_error(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 3: Failed task (cli_error)")
    print("─" * 60)

    task_id = await make_task(project_id, goal_id, "cli-error-fail")
    run = await create_and_complete_run(
        task_id, project_id, goal_id,
        error_message="CLI binary 'glm' not found in PATH",
        failure_type="cli_error",
        provider="glm_coding",
        model="glm-4-plus",
    )

    check("status is failed", run.status == "failed", f"got {run.status}")
    check("feedback_score is 0.0", run.feedback_score == 0.0, f"got {run.feedback_score}")
    check("failure_classification is 'cli_error'", run.failure_classification == "cli_error", f"got {run.failure_classification}")
    check("retry_eligible is True", run.retry_eligible is True, f"got {run.retry_eligible}")
    check("retry_reason mentions alternate", "alternate" in (run.retry_reason or "").lower(), f"got {run.retry_reason}")


# ────────────────────────────────────────────────────────────────────
# Test 4: Failed task — validation_failed
# ────────────────────────────────────────────────────────────────────

async def test_failed_validation(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 4: Failed task (validation_failed)")
    print("─" * 60)

    task_id = await make_task(project_id, goal_id, "validation-fail")
    run = await create_and_complete_run(
        task_id, project_id, goal_id,
        error_message="Output failed schema validation: missing required field 'result'",
        failure_type="validation_failed",
    )

    check("status is failed", run.status == "failed", f"got {run.status}")
    check("feedback_score is 0.0", run.feedback_score == 0.0, f"got {run.feedback_score}")
    check("failure_classification is 'validation_failed'", run.failure_classification == "validation_failed", f"got {run.failure_classification}")
    check("retry_eligible is False", run.retry_eligible is False, f"got {run.retry_eligible}")
    check("retry_reason says fix code", "fix code" in (run.retry_reason or "").lower(), f"got {run.retry_reason}")


# ────────────────────────────────────────────────────────────────────
# Test 5: POST /api/feedback/run/{run_id} — reprocess feedback
# ────────────────────────────────────────────────────────────────────

async def test_feedback_endpoint(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 5: POST /api/feedback/run/{run_id}")
    print("─" * 60)

    task_id = await make_task(project_id, goal_id, "feedback-ep")
    # Create a failed run, then manually clear its feedback fields to simulate stale state
    run = await create_and_complete_run(
        task_id, project_id, goal_id,
        error_message="Model returned 502",
        failure_type="model_error",
    )
    run_id = run.id

    # Clear feedback fields to test reprocessing
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        r = result.scalars().first()
        r.feedback_score = None
        r.failure_classification = None
        await db.commit()

    # Call FeedbackService.process_run directly (simulates what the endpoint does)
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        r = result.scalars().first()
        feedback = FeedbackService().process_run(r)
        r.feedback_score = feedback.quality_score
        r.failure_classification = feedback.failure_classification
        await db.commit()

    # Verify DB persistence
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        loaded = result.scalars().first()

    check("reprocessed feedback_score persisted", loaded.feedback_score == 0.0, f"got {loaded.feedback_score}")
    check("reprocessed failure_classification persisted", loaded.failure_classification == "model_error", f"got {loaded.failure_classification}")
    check("run_id matches", feedback.run_id == run_id)


# ────────────────────────────────────────────────────────────────────
# Test 6: POST /api/retry/evaluate/{run_id} — evaluate retry
# ────────────────────────────────────────────────────────────────────

async def test_retry_evaluate_endpoint(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 6: POST /api/retry/evaluate/{run_id}")
    print("─" * 60)

    task_id = await make_task(project_id, goal_id, "retry-ep")
    # Create a failed timeout run, then clear retry fields
    run = await create_and_complete_run(
        task_id, project_id, goal_id,
        error_message="Process timed out after 300s",
        failure_type="timeout",
    )
    run_id = run.id

    # Clear retry fields to simulate re-evaluation
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        r = result.scalars().first()
        r.retry_eligible = None
        r.retry_reason = None
        await db.commit()

    # Call RetryIntelligence.evaluate directly (simulates endpoint)
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        r = result.scalars().first()
        retry = RetryIntelligence().evaluate(r)
        r.retry_eligible = retry.eligible
        r.retry_reason = retry.reason
        await db.commit()

    # Verify DB persistence
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        loaded = result.scalars().first()

    check("re-evaluated retry_eligible persisted", loaded.retry_eligible is True, f"got {loaded.retry_eligible}")
    check("re-evaluated retry_reason persisted", "timeout" in (loaded.retry_reason or ""), f"got {loaded.retry_reason}")
    check("strategy is same_provider", retry.strategy == "same_provider", f"got {retry.strategy}")
    check("max_retries is 1", retry.max_retries == 1, f"got {retry.max_retries}")

    # Test re-evaluation of a validation_failed run (should stay ineligible)
    val_task_id = await make_task(project_id, goal_id, "retry-val-fail")
    val_run = await create_and_complete_run(
        val_task_id, project_id, goal_id,
        error_message="Validation failed",
        failure_type="validation_failed",
    )
    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == val_run.id))
        r = result.scalars().first()
        r.retry_eligible = None
        r.retry_reason = None
        await db.commit()

    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == val_run.id))
        r = result.scalars().first()
        retry = RetryIntelligence().evaluate(r)
        r.retry_eligible = retry.eligible
        r.retry_reason = retry.reason
        await db.commit()

    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == val_run.id))
        loaded = result.scalars().first()

    check("validation_failed re-eval: not eligible", loaded.retry_eligible is False, f"got {loaded.retry_eligible}")
    check("validation_failed re-eval: strategy none", retry.strategy == "none", f"got {retry.strategy}")


# ────────────────────────────────────────────────────────────────────
# Test 7: POST /api/learning/analyze — full pipeline
# ────────────────────────────────────────────────────────────────────

async def test_learning_analyze(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 7: POST /api/learning/analyze")
    print("─" * 60)

    rm = RunManager()
    success_task_id = await make_task(project_id, goal_id, "learning-success")

    # Create enough failed runs to meet the _MIN_RUNS_FAILURE threshold (3)
    for i in range(5):
        fail_task = Task(project_id=project_id, content=f"fail task {i}", goal_id=goal_id)
        async with async_session() as db:
            db.add(fail_task)
            await db.flush()
            tid = fail_task.id
            await db.commit()

        await create_and_complete_run(
            tid, project_id, goal_id,
            error_message=f"CLI timeout attempt {i}",
            failure_type="timeout",
            provider="glm_coding",
            model="glm-4-plus",
        )

    # Create enough runs to meet _MIN_RUNS_COST threshold (8)
    for i in range(4):
        await create_and_complete_run(success_task_id, project_id, goal_id)

    # Run analysis via RDManager (simulates what the endpoint does)
    from app.services.rd_manager import RDManager

    proposals = []
    async with async_session() as db:
        rd = RDManager()
        proposals = await rd.submit_to_research(project_id=project_id, db=db)
        await db.commit()

    check("proposals were created", len(proposals) > 0, f"got {len(proposals)} proposals")

    if proposals:
        # Verify at least one proposal exists in DB
        async with async_session() as db:
            result = await db.execute(
                select(ImprovementProposal).where(
                    ImprovementProposal.project_id == project_id,
                )
            )
            db_proposals = list(result.scalars().all())

        check("proposals persisted to DB", len(db_proposals) > 0, f"got {len(db_proposals)}")
        check("proposal status is draft", all(p.status == "draft" for p in db_proposals))

        # Check proposal fields are populated
        p = db_proposals[0]
        check("proposal has title", bool(p.title), f"title='{p.title}'")
        check("proposal has problem_description", bool(p.problem_description))
        check("proposal has risk_level", bool(p.risk_level), f"risk_level={p.risk_level}")
        check("proposal has effort", bool(p.implementation_effort), f"effort={p.implementation_effort}")
    else:
        # Even with 5 timeout failures, check if analyzer found patterns
        check("WARNING: no proposals (may be expected if thresholds not met)", False, "no proposals created from 5 timeout failures")

    # Verify findings were produced by the analyzer directly
    from app.services.research_analyzer import ResearchAnalyzer
    async with async_session() as db:
        analyzer = ResearchAnalyzer()
        findings = await analyzer.analyze_project(project_id, db)

    check("analyzer produced findings", len(findings) > 0, f"got {len(findings)} findings")

    if findings:
        f = findings[0]
        check("finding has finding_type", bool(f.finding_type), f"type={f.finding_type}")
        check("finding has severity", bool(f.severity), f"severity={f.severity}")
        check("finding has title", bool(f.title), f"title={f.title}")
        check("finding has related_run_ids", len(f.related_run_ids) > 0, f"runs={len(f.related_run_ids)}")
        check("finding has confidence_score", f.confidence_score > 0, f"confidence={f.confidence_score}")
        check("finding has root_cause_tag", bool(f.root_cause_tag), f"tag={f.root_cause_tag}")


# ────────────────────────────────────────────────────────────────────
# Test 8: Edge cases — retry_count boundary, max retries
# ────────────────────────────────────────────────────────────────────

async def test_retry_edge_cases(project_id, goal_id):
    print("\n" + "─" * 60)
    print("TEST 8: Edge cases — retry_count boundary, max retries")
    print("─" * 60)

    task_id = await make_task(project_id, goal_id, "edge-case")

    # retry_count=1 with timeout should still be eligible
    async with async_session() as db:
        run = Run(
            task_id=task_id, project_id=project_id, goal_id=goal_id,
            agent_type="backend", status="failed",
            retry_count=1, failure_type="timeout",
        )
        db.add(run)
        await db.flush()
        rid = run.id
        await db.commit()

    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == rid))
        r = result.scalars().first()
        retry = RetryIntelligence().evaluate(r)

    check("retry_count=1 timeout still eligible", retry.eligible is True, f"got {retry.eligible}")
    check("retry_count=1 strategy same_provider", retry.strategy == "same_provider")

    # retry_count=2 should NOT be eligible
    async with async_session() as db:
        run2 = Run(
            task_id=task_id, project_id=project_id, goal_id=goal_id,
            agent_type="backend", status="failed",
            retry_count=2, failure_type="timeout",
        )
        db.add(run2)
        await db.flush()
        rid2 = run2.id
        await db.commit()

    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == rid2))
        r = result.scalars().first()
        retry2 = RetryIntelligence().evaluate(r)

    check("retry_count=2 NOT eligible", retry2.eligible is False, f"got {retry2.eligible}")
    check("retry_count=2 reason max retries", "max retries" in retry2.reason)
    check("retry_count=2 strategy none", retry2.strategy == "none")
    check("retry_count=2 max_retries 0", retry2.max_retries == 0)


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

async def main():
    await init_db()

    print("=" * 60)
    print("Phase 6A: Real-World Validation — E2E Tests")
    print("=" * 60)

    project_id, goal_id = await seed_project()

    try:
        await test_successful_task(project_id, goal_id)
        await test_failed_timeout(project_id, goal_id)
        await test_failed_cli_error(project_id, goal_id)
        await test_failed_validation(project_id, goal_id)
        await test_feedback_endpoint(project_id, goal_id)
        await test_retry_evaluate_endpoint(project_id, goal_id)
        await test_learning_analyze(project_id, goal_id)
        await test_retry_edge_cases(project_id, goal_id)
    except Exception as e:
        import traceback
        print(f"\nFATAL: {e}")
        traceback.print_exc()
        results.append(("test suite completion", False, str(e)))

    # ── Summary ──
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60 + "\n")

    passed = sum(1 for _, ok, _ in results if ok)
    failed_checks = [(n, d) for n, ok, d in results if not ok]
    total = len(results)

    print(f"  Total checks: {total}")
    print(f"  Passed:       {passed}")
    print(f"  Failed:       {total - passed}")
    print()

    if failed_checks:
        print("  FAILED CHECKS:")
        for name, detail in failed_checks:
            print(f"    [FAIL] {name} {detail}")
        print()
    else:
        print("  All checks passed.")
        print()

    # ── Bug Report ──
    print("  BUG REPORT:")
    bugs = []
    for name, detail in failed_checks:
        bugs.append(f"    - {name}: {detail}" if detail else f"    - {name}")

    if bugs:
        for b in bugs:
            print(b)
    else:
        print("    No bugs found.")
    print()

    return 1 if failed_checks else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
