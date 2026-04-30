"""Safety gates for controlled auto-execution. Five gates, first failure short-circuits."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, and_

from app.models import ActivityLog


@dataclass
class SafetyResult:
    passed: bool
    gate: str
    reason: str


class SafetyEngine:

    async def evaluate(self, proposal, db) -> SafetyResult:
        r = await self._gate_approval(proposal)
        if not r.passed:
            return r

        r = await self._gate_budget(db)
        if not r.passed:
            return r

        r = await self._gate_velocity(proposal, db)
        if not r.passed:
            return r

        r = await self._gate_duplicate(proposal, db)
        if not r.passed:
            return r

        r = await self._gate_failure_rate(db)
        if not r.passed:
            return r

        return SafetyResult(passed=True, gate="all", reason="passed")

    async def _gate_approval(self, proposal) -> SafetyResult:
        if proposal.status != "approved":
            return SafetyResult(False, "approval", f"status is '{proposal.status}', not 'approved'")
        if not getattr(proposal, "guard_confirmed", False):
            return SafetyResult(False, "approval", "guard_confirmed is false")
        if not getattr(proposal, "auto_execution_eligible", False):
            return SafetyResult(False, "approval", "auto_execution_eligible is false")
        return SafetyResult(True, "approval", "ok")

    async def _gate_budget(self, db) -> SafetyResult:
        try:
            from app.services.budget_manager import BudgetManager
            bm = BudgetManager()
            state = await bm.get_state(db)
            if state == "blocked":
                return SafetyResult(False, "budget", "budget_blocked")
            if state == "throttled":
                return SafetyResult(False, "budget", "budget_throttled")
        except Exception:
            pass
        return SafetyResult(True, "budget", "ok")

    async def _gate_velocity(self, proposal, db) -> SafetyResult:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        result = await db.execute(
            select(func.count()).select_from(ActivityLog).where(
                ActivityLog.action == "auto_executed",
                ActivityLog.timestamp >= cutoff,
            )
        )
        count = result.scalar() or 0
        if count >= 1:
            return SafetyResult(False, "velocity", "velocity_limit")
        return SafetyResult(True, "velocity", "ok")

    async def _gate_duplicate(self, proposal, db) -> SafetyResult:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await db.execute(
            select(func.count()).select_from(ActivityLog).where(
                ActivityLog.action == "auto_executed",
                ActivityLog.details.contains(proposal.title),
                ActivityLog.timestamp >= cutoff,
            )
        )
        count = result.scalar() or 0
        if count >= 1:
            return SafetyResult(False, "duplicate", "duplicate_execution")
        return SafetyResult(True, "duplicate", "ok")

    async def _gate_failure_rate(self, db) -> SafetyResult:
        result = await db.execute(
            select(ActivityLog).where(
                ActivityLog.action.in_(["auto_executed", "auto_execution_failed"]),
            ).order_by(ActivityLog.timestamp.desc()).limit(10)
        )
        recent = list(result.scalars().all())
        if len(recent) >= 6:
            failures = sum(1 for e in recent if e.action == "auto_execution_failed")
            if failures / len(recent) > 0.5:
                return SafetyResult(False, "failure_rate", "high_failure_rate")
        return SafetyResult(True, "failure_rate", "ok")
