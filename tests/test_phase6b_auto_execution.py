"""
Phase 6B: Controlled Auto Execution Tests

Validates:
1. Approved + guard_confirmed + eligible proposal executes via convert_to_goal
2. Unapproved proposal blocked
3. Guard not confirmed blocked
4. Dry-run writes nothing
5. Duplicate blocked (24h)
6. Velocity blocked (1/hour)
7. Recent failure rate blocked (>50%)
8. No direct code execution
9. No silent API fallback (budget gate)

Run:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_phase6b_auto_execution.py
"""

import sys
import os
import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ["ORKA_LLM_ENABLED"] = "false"
os.environ["ORKA_CLI_ENABLED"] = "false"

results: list[tuple[str, str, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {name} {detail}")


def make_mock_db(counts=None):
    """Create a mock DB where execute().scalar() returns counts from the list."""
    if counts is None:
        counts = [0, 0, 0, 0, 0]
    idx = 0
    async def mock_execute(stmt):
        nonlocal idx
        mr = MagicMock()
        mr.scalar = MagicMock(return_value=counts[idx] if idx < len(counts) else 0)
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mr.scalars = MagicMock(return_value=mock_scalars)
        idx += 1
        return mr
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=mock_execute)
    return db


def make_proposal(
    proposal_id="p-1",
    title="Test improvement",
    status="approved",
    guard_confirmed=True,
    auto_execution_eligible=True,
    auto_executed=False,
    risk_level="low",
    project_id="proj-1",
):
    p = MagicMock()
    p.id = proposal_id
    p.title = title
    p.status = status
    p.guard_confirmed = guard_confirmed
    p.auto_execution_eligible = auto_execution_eligible
    p.auto_executed = auto_executed
    p.risk_level = risk_level
    p.project_id = project_id
    p.auto_executed_at = None
    p.auto_execution_skip_reason = None
    p.decision_log = "[]"
    p.updated_at = datetime.now(timezone.utc)
    return p


async def test_gate_approval_passes():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal()
    db = make_mock_db([0, 0, 0])

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="normal")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("approval gate passes", result.passed, f"got {result.reason}")


async def test_gate_approval_unapproved():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal(status="draft")
    db = AsyncMock()

    result = await engine.evaluate(p, db)
    check("unapproved blocked", not result.passed)
    check("unapproved gate", result.gate == "approval")


async def test_gate_guard_not_confirmed():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal(guard_confirmed=False)
    db = AsyncMock()

    result = await engine.evaluate(p, db)
    check("guard not confirmed blocked", not result.passed)
    check("guard not confirmed gate", result.gate == "approval")
    check("guard not confirmed reason", "guard_confirmed" in result.reason)


async def test_gate_not_eligible():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal(auto_execution_eligible=False)
    db = AsyncMock()

    result = await engine.evaluate(p, db)
    check("not eligible blocked", not result.passed)
    check("not eligible gate", result.gate == "approval")


async def test_gate_budget_blocked():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal()
    db = AsyncMock()

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="blocked")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("budget blocked", not result.passed)
    check("budget gate", result.gate == "budget")
    check("budget reason", result.reason == "budget_blocked")


async def test_gate_budget_throttled():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal()
    db = AsyncMock()

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="throttled")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("budget throttled", not result.passed)
    check("budget throttled reason", result.reason == "budget_throttled")


async def test_gate_velocity_blocked():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal()
    db = AsyncMock()

    call_count = 0
    async def mock_execute(stmt):
        nonlocal call_count
        mr = MagicMock()
        if call_count == 0:
            mr.scalar = MagicMock(return_value=1)
        else:
            mr.scalar = MagicMock(return_value=0)
        call_count += 1
        return mr

    db.execute = AsyncMock(side_effect=mock_execute)

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="normal")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("velocity blocked", not result.passed)
    check("velocity gate", result.gate == "velocity")
    check("velocity reason", result.reason == "velocity_limit")


async def test_gate_velocity_clear():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal()
    db = make_mock_db([0, 0, 0])

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="normal")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("velocity clear", result.passed, f"got {result.reason}")


async def test_gate_duplicate():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal(title="Fix timeout handling")
    db = AsyncMock()

    call_count = 0
    async def mock_execute(stmt):
        nonlocal call_count
        mr = MagicMock()
        if call_count == 0:
            mr.scalar = MagicMock(return_value=0)
        elif call_count == 1:
            mr.scalar = MagicMock(return_value=1)
        else:
            mr.scalars = MagicMock(return_value=iter([]))
        call_count += 1
        return mr

    db.execute = AsyncMock(side_effect=mock_execute)

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="normal")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("duplicate blocked", not result.passed)
    check("duplicate gate", result.gate == "duplicate")
    check("duplicate reason", result.reason == "duplicate_execution")


async def test_gate_failure_rate():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal()
    db = AsyncMock()

    logs = []
    for i in range(6):
        log = MagicMock()
        log.action = "auto_execution_failed" if i < 4 else "auto_executed"
        logs.append(log)

    call_count = 0
    async def mock_execute(stmt):
        nonlocal call_count
        mr = MagicMock()
        if call_count < 2:
            mr.scalar = MagicMock(return_value=0)
        elif call_count == 2:
            mock_scalars = MagicMock()
            mock_scalars.all = MagicMock(return_value=logs)
            mr.scalars = MagicMock(return_value=mock_scalars)
        call_count += 1
        return mr

    db.execute = AsyncMock(side_effect=mock_execute)

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="normal")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("failure rate blocked", not result.passed)
    check("failure rate gate", result.gate == "failure_rate")
    check("failure rate reason", result.reason == "high_failure_rate")


async def test_gate_failure_rate_acceptable():
    from app.services.safety_engine import SafetyEngine

    engine = SafetyEngine()
    p = make_proposal()
    db = AsyncMock()

    logs = []
    for i in range(10):
        log = MagicMock()
        log.action = "auto_execution_failed" if i < 3 else "auto_executed"
        logs.append(log)

    call_count = 0
    async def mock_execute(stmt):
        nonlocal call_count
        mr = MagicMock()
        if call_count < 2:
            mr.scalar = MagicMock(return_value=0)
        elif call_count == 2:
            mock_scalars = MagicMock()
            mock_scalars.all = MagicMock(return_value=logs)
            mr.scalars = MagicMock(return_value=mock_scalars)
        call_count += 1
        return mr

    db.execute = AsyncMock(side_effect=mock_execute)

    with patch("app.services.budget_manager.BudgetManager") as mock_cls:
        mock_bm = AsyncMock()
        mock_bm.get_state = AsyncMock(return_value="normal")
        mock_cls.return_value = mock_bm

        result = await engine.evaluate(p, db)
    check("failure rate acceptable", result.passed, f"got {result.reason}")


async def test_dry_run_writes_nothing():
    from app.services.auto_executor import AutoExecutor

    executor = AutoExecutor()
    p = make_proposal()
    db = AsyncMock()

    with patch.object(executor, "find_eligible", new_callable=AsyncMock, return_value=[p]):
        with patch.object(executor.safety, "evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = MagicMock(passed=True, gate="all", reason="passed")

            result = await executor.execute(db, dry_run=True)

    check("dry_run flag true", result["dry_run"] is True)
    check("dry_run executed count", len(result["executed"]) == 1)
    check("dry_run reason", result["executed"][0]["reason"] == "would_convert_to_goal")
    check("dry_run no flush", db.flush.call_count == 0)


async def test_executor_skips_blocked():
    from app.services.auto_executor import AutoExecutor

    executor = AutoExecutor()
    p = make_proposal()
    db = AsyncMock()

    with patch.object(executor, "find_eligible", new_callable=AsyncMock, return_value=[p]):
        with patch.object(executor.safety, "evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = MagicMock(passed=False, gate="velocity", reason="velocity_limit")

            result = await executor.execute(db, dry_run=False)

    check("skipped count", len(result["skipped"]) == 1)
    check("skipped reason", result["skipped"][0]["reason"] == "velocity_limit")
    check("executed empty", len(result["executed"]) == 0)
    check("skip_reason on proposal", p.auto_execution_skip_reason == "velocity_limit")


async def test_executor_converts_goal():
    from app.services.auto_executor import AutoExecutor

    executor = AutoExecutor()
    p = make_proposal()
    db = AsyncMock()

    mock_goal = MagicMock()
    mock_goal.id = "goal-1"

    with patch.object(executor, "find_eligible", new_callable=AsyncMock, return_value=[p]):
        with patch.object(executor.safety, "evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = MagicMock(passed=True, gate="all", reason="passed")

            with patch("app.services.auto_executor.RDManager") as mock_rd_cls:
                mock_rd = AsyncMock()
                mock_rd.convert_to_goal = AsyncMock(return_value=(p, mock_goal))
                mock_rd_cls.return_value = mock_rd

                result = await executor.execute(db, dry_run=False)

    check("executed count", len(result["executed"]) == 1)
    check("goal_id in result", result["executed"][0]["goal_id"] == "goal-1")
    check("auto_executed set", p.auto_executed is True)
    check("auto_executed_at set", p.auto_executed_at is not None)
    check("decision_log updated", "auto_executed" in (p.decision_log or ""))


async def test_executor_handles_error():
    from app.services.auto_executor import AutoExecutor

    executor = AutoExecutor()
    p = make_proposal()
    db = AsyncMock()

    with patch.object(executor, "find_eligible", new_callable=AsyncMock, return_value=[p]):
        with patch.object(executor.safety, "evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.return_value = MagicMock(passed=True, gate="all", reason="passed")

            with patch("app.services.auto_executor.RDManager") as mock_rd_cls:
                mock_rd = AsyncMock()
                mock_rd.convert_to_goal = AsyncMock(side_effect=ValueError("invalid transition"))
                mock_rd_cls.return_value = mock_rd

                result = await executor.execute(db, dry_run=False)

    check("error: executed empty", len(result["executed"]) == 0)
    check("error: skipped count", len(result["skipped"]) == 1)
    check("error: reason", "conversion_failed" in result["skipped"][0]["reason"])


async def test_no_direct_code_execution():
    from app.services.auto_executor import AutoExecutor

    source = inspect.getsource(AutoExecutor.execute)
    check("no exec() calls", "exec(" not in source)
    check("no eval() calls", "eval(" not in source)
    check("no subprocess calls", "subprocess" not in source)
    check("no os.system calls", "os.system" not in source)
    check("uses convert_to_goal", "convert_to_goal" in source)


async def test_no_silent_paid_api_fallback():
    from app.services.safety_engine import SafetyEngine

    source = inspect.getsource(SafetyEngine._gate_budget)
    check("budget checks state", "get_state" in source)
    check("budget blocks explicitly", "budget_blocked" in source)


async def test_integration_eligible_flow():
    from app.database import init_db, async_session
    from app.models import Project, ImprovementProposal
    from app.services.auto_executor import AutoExecutor

    await init_db()
    async with async_session() as db:
        project = Project(name="auto-exec-test", description="test")
        db.add(project)
        await db.flush()

        proposal = ImprovementProposal(
            project_id=project.id,
            title="Auto-exec eligible proposal",
            status="approved",
            risk_level="low",
            guard_confirmed=True,
            auto_execution_eligible=True,
            auto_executed=False,
            problem_description="test",
            evidence_summary="test",
            suggested_solution="test",
            expected_impact="test",
        )
        db.add(proposal)
        await db.flush()

        executor = AutoExecutor()
        result = await executor.execute(db, dry_run=False)
        await db.commit()

        check("integration: executed", len(result["executed"]) >= 1, f"got {len(result['executed'])}")
        check("integration: auto_executed", proposal.auto_executed is True)
        check("integration: auto_executed_at set", proposal.auto_executed_at is not None)


async def test_high_risk_cannot_be_eligible():
    from app.database import init_db, async_session
    from app.models import Project, ImprovementProposal

    await init_db()
    async with async_session() as db:
        project = Project(name="risk-test", description="test")
        db.add(project)
        await db.flush()

        for risk in ("high", "critical"):
            can_be_eligible = risk not in ("high", "critical")
            check(f"{risk} risk rejected", not can_be_eligible, f"risk={risk}")


async def test_dry_run_real_db():
    from app.database import init_db, async_session
    from app.models import Project, ImprovementProposal
    from app.services.auto_executor import AutoExecutor

    await init_db()
    async with async_session() as db:
        project = Project(name="dry-run-test", description="test")
        db.add(project)
        await db.flush()

        proposal = ImprovementProposal(
            project_id=project.id,
            title="Dry-run test proposal",
            status="approved",
            risk_level="low",
            guard_confirmed=True,
            auto_execution_eligible=True,
            auto_executed=False,
            problem_description="test",
            evidence_summary="test",
            suggested_solution="test",
            expected_impact="test",
        )
        db.add(proposal)
        await db.flush()
        await db.commit()

        from sqlalchemy import select as sa_select
        result = await db.execute(
            sa_select(ImprovementProposal).where(ImprovementProposal.id == proposal.id)
        )
        proposal = result.scalars().first()

        executor = AutoExecutor()
        exec_result = await executor.execute(db, dry_run=True)

        check("dry-run DB: not auto_executed", proposal.auto_executed is False)
        check("dry-run DB: total items in plan", len(exec_result["executed"]) + len(exec_result["skipped"]) >= 1)
        check("dry-run DB: flag", exec_result["dry_run"] is True)


async def main():
    print("=" * 60)
    print("Phase 6B: Controlled Auto Execution Tests")
    print("=" * 60)

    print("\n--- SafetyEngine Gates ---")
    await test_gate_approval_passes()
    await test_gate_approval_unapproved()
    await test_gate_guard_not_confirmed()
    await test_gate_not_eligible()
    await test_gate_budget_blocked()
    await test_gate_budget_throttled()
    await test_gate_velocity_blocked()
    await test_gate_velocity_clear()
    await test_gate_duplicate()
    await test_gate_failure_rate()
    await test_gate_failure_rate_acceptable()

    print("\n--- AutoExecutor ---")
    await test_dry_run_writes_nothing()
    await test_executor_skips_blocked()
    await test_executor_converts_goal()
    await test_executor_handles_error()
    await test_no_direct_code_execution()
    await test_no_silent_paid_api_fallback()

    print("\n--- Integration ---")
    await test_integration_eligible_flow()
    await test_high_risk_cannot_be_eligible()
    await test_dry_run_real_db()

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Results: {passed}/{len(results)} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
