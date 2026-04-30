"""AutoExecutor: converts eligible proposals to Goals/Tasks via RDManager.

Hard rule: creates Goal/Task records only. Does NOT start worker execution.
Task execution remains manual or user-triggered through existing flows.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import select, and_

from app.models import ImprovementProposal, ActivityLog
from app.services.safety_engine import SafetyEngine
from app.services.rd_manager import RDManager


class AutoExecutor:

    def __init__(self):
        self.safety = SafetyEngine()

    async def find_eligible(self, db) -> list[ImprovementProposal]:
        result = await db.execute(
            select(ImprovementProposal).where(
                ImprovementProposal.status == "approved",
                ImprovementProposal.auto_execution_eligible.is_(True),
                ImprovementProposal.auto_executed.is_(False),
            )
        )
        return list(result.scalars().all())

    async def execute(self, db, dry_run: bool = False) -> dict:
        proposals = await self.find_eligible(db)
        executed = []
        skipped = []

        for proposal in proposals:
            safety_result = await self.safety.evaluate(proposal, db)

            if not safety_result.passed:
                skipped.append({
                    "proposal_id": proposal.id,
                    "title": proposal.title,
                    "reason": safety_result.reason,
                })
                if not dry_run:
                    proposal.auto_execution_skip_reason = safety_result.reason
                    db.add(ActivityLog(
                        project_id=proposal.project_id,
                        action="auto_execution_skipped",
                        details=json.dumps({
                            "proposal_id": proposal.id,
                            "title": proposal.title,
                            "gate": safety_result.gate,
                            "reason": safety_result.reason,
                        }),
                    ))
                    proposal.updated_at = datetime.now(timezone.utc)
                    await db.flush()
                continue

            if dry_run:
                executed.append({
                    "proposal_id": proposal.id,
                    "title": proposal.title,
                    "reason": "would_convert_to_goal",
                })
                continue

            try:
                rd = RDManager()
                _, goal = await rd.convert_to_goal(proposal.id, db)

                proposal.auto_executed = True
                proposal.auto_executed_at = datetime.now(timezone.utc)
                self._log_decision(proposal, "auto_executed", goal.id)

                db.add(ActivityLog(
                    project_id=proposal.project_id,
                    action="auto_executed",
                    details=json.dumps({
                        "proposal_id": proposal.id,
                        "title": proposal.title,
                        "goal_id": goal.id,
                    }),
                ))
                proposal.updated_at = datetime.now(timezone.utc)
                await db.flush()

                executed.append({
                    "proposal_id": proposal.id,
                    "title": proposal.title,
                    "goal_id": goal.id,
                })
            except Exception as e:
                skipped.append({
                    "proposal_id": proposal.id,
                    "title": proposal.title,
                    "reason": f"conversion_failed: {e}",
                })
                db.add(ActivityLog(
                    project_id=proposal.project_id,
                    action="auto_execution_failed",
                    details=json.dumps({
                        "proposal_id": proposal.id,
                        "title": proposal.title,
                        "error": str(e),
                    }),
                ))
                await db.flush()

        return {
            "dry_run": dry_run,
            "executed": executed,
            "skipped": skipped,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _log_decision(self, proposal, action: str, goal_id: str | None = None) -> None:
        log = json.loads(proposal.decision_log or "[]")
        entry = {
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if goal_id:
            entry["goal_id"] = goal_id
        log.append(entry)
        proposal.decision_log = json.dumps(log)
