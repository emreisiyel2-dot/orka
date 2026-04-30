"""Orchestrates the R&D / Improvement Lab workflow with strict status transitions."""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImprovementProposal, Goal, Run, Task, Agent, ActivityLog
from app.schemas import ApprovalGuardResponse

_DEV_MODE = os.getenv("ORKA_DEV_MODE", "false").lower() == "true"


_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"under_review", "archived"},
    "under_review": {"approved", "rejected"},
    "approved": {"converted_to_goal"},
    "rejected": {"archived"},
    "converted_to_goal": set(),
    "archived": set(),
}


@dataclass
class ApprovalGuard:
    estimated_runs: int = 0
    estimated_cost_usd: float = 0.0
    requires_paid_provider: bool = False
    budget_remaining_usd: float = 0.0
    budget_fits: bool = True
    risk_level: str = "medium"
    affected_systems: list[str] = field(default_factory=list)
    has_breaking_changes: bool = False
    rollback_possible: bool = True
    rollback_plan: str = "Tasks can be marked as failed; no code changes without approval."
    can_proceed: bool = True
    warnings: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)


class RDManager:

    def _validate_transition(self, current: str, target: str) -> None:
        allowed = _TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid transition: {current} → {target}. "
                f"Allowed: {allowed or 'none (terminal state)'}"
            )

    async def submit_to_research(
        self,
        project_id: str,
        goal_id: str | None = None,
        analysis_types: list[str] | None = None,
        db: AsyncSession | None = None,
    ) -> list[ImprovementProposal]:
        if db is None:
            return []

        from app.services.research_analyzer import ResearchAnalyzer
        from app.services.proposal_generator import ProposalGenerator

        analyzer = ResearchAnalyzer()
        generator = ProposalGenerator()

        findings = await analyzer.analyze_project(project_id, db)

        if analysis_types:
            findings = [f for f in findings if f.finding_type in analysis_types]

        return await generator.generate_from_analysis(
            project_id=project_id,
            findings=findings,
            source_goal_id=goal_id,
            db=db,
        )

    async def submit_for_review(
        self, proposal_id: str, db: AsyncSession,
    ) -> ImprovementProposal:
        proposal = await self._get_proposal(proposal_id, db)
        self._validate_transition(proposal.status, "under_review")
        proposal.status = "under_review"
        proposal.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return proposal

    async def run_approval_guard(
        self, proposal_id: str, db: AsyncSession,
    ) -> ApprovalGuardResponse:
        proposal = await self._get_proposal(proposal_id, db)

        estimated_runs = 4
        estimated_cost, requires_paid = await self._estimate_implementation_cost(db)

        warnings = []
        blocks = []

        # Check budget
        budget_remaining = 0.0
        budget_fits = True
        try:
            from app.services.budget_manager import BudgetManager
            bm = BudgetManager()
            state = await bm.get_state(db)
            if state == "blocked":
                budget_fits = False
            budget_status = await bm.get_status(db)
            budget_remaining = budget_status.daily_hard_limit - budget_status.daily_spend
        except Exception as e:
            budget_fits = False
            blocks.append(f"Budget check failed: {e}. Cannot proceed without budget verification.")

        if estimated_cost > budget_remaining and requires_paid:
            budget_fits = False

        # Risk assessment
        risk_level = proposal.risk_level
        affected = json.loads(proposal.affected_agents)
        areas = json.loads(proposal.affected_areas)
        has_breaking = risk_level in ("high", "critical")
        if requires_paid:
            warnings.append("Implementation requires paid API provider — no CLI available")
        if not budget_fits:
            if _DEV_MODE:
                warnings.append(
                    f"[DEV MODE] Budget advisory: ${estimated_cost:.2f} needed, "
                    f"${budget_remaining:.2f} remaining — proceeding allowed"
                )
            else:
                blocks.append(f"Budget insufficient: ${estimated_cost:.2f} needed, ${budget_remaining:.2f} remaining")
        if risk_level == "critical":
            warnings.append("Proposal rated critical risk — review carefully before proceeding")

        can_proceed = len(blocks) == 0

        guard = ApprovalGuard(
            estimated_runs=estimated_runs,
            estimated_cost_usd=estimated_cost,
            requires_paid_provider=requires_paid,
            budget_remaining_usd=budget_remaining,
            budget_fits=budget_fits,
            risk_level=risk_level,
            affected_systems=areas,
            has_breaking_changes=has_breaking,
            rollback_possible=True,
            rollback_plan="Tasks can be marked as failed; no code changes without explicit approval.",
            can_proceed=can_proceed,
            warnings=warnings,
            blocks=blocks,
        )

        # Persist guard data on proposal
        proposal.guard_quota_impact = json.dumps({
            "estimated_runs": estimated_runs,
            "estimated_cost_usd": estimated_cost,
            "requires_paid_provider": requires_paid,
            "budget_remaining_usd": budget_remaining,
            "budget_fits": budget_fits,
            "dev_mode": _DEV_MODE,
        })
        proposal.guard_risk_assessment = json.dumps({
            "risk_level": risk_level,
            "affected_systems": areas,
            "has_breaking_changes": has_breaking,
            "rollback_possible": True,
            "rollback_plan": guard.rollback_plan,
        })
        proposal.updated_at = datetime.now(timezone.utc)
        await db.flush()

        return ApprovalGuardResponse(
            estimated_runs=guard.estimated_runs,
            estimated_cost_usd=guard.estimated_cost_usd,
            requires_paid_provider=guard.requires_paid_provider,
            budget_remaining_usd=guard.budget_remaining_usd,
            budget_fits=guard.budget_fits,
            risk_level=guard.risk_level,
            affected_systems=guard.affected_systems,
            has_breaking_changes=guard.has_breaking_changes,
            rollback_possible=guard.rollback_possible,
            rollback_plan=guard.rollback_plan,
            can_proceed=guard.can_proceed,
            warnings=guard.warnings,
            blocks=guard.blocks,
        )

    async def _estimate_implementation_cost(self, db: AsyncSession) -> tuple[float, bool]:
        """Estimate cost from actual UsageRecord data. Returns (cost, requires_paid)."""
        try:
            from app.models import UsageRecord
            result = await db.execute(
                select(UsageRecord).order_by(UsageRecord.created_at.desc()).limit(10)
            )
            records = list(result.scalars().all())

            if records:
                avg_cost = sum(r.cost_usd for r in records) / len(records)
                return avg_cost * 4, any(r.cost_usd > 0 for r in records)
        except Exception:
            pass

        # No usage records — estimate from provider config
        try:
            from app.providers.registry import ProviderRegistry
            from app.config.model_config import load_config
            config = load_config()
            registry = ProviderRegistry(config)
            if registry.has_cli_providers():
                return 0.0, False
        except Exception:
            pass

        return 4 * 0.05, True

    async def approve_proposal(
        self,
        proposal_id: str,
        reviewer: str = "user",
        notes: str | None = None,
        guard_confirmed: bool = False,
        db: AsyncSession | None = None,
    ) -> ImprovementProposal:
        if db is None:
            raise ValueError("Database session required")
        proposal = await self._get_proposal(proposal_id, db)
        self._validate_transition(proposal.status, "approved")
        if not guard_confirmed:
            raise ValueError(
                "Approval requires guard_confirmed=True. "
                "Run run_approval_guard() first and review the result."
            )
        proposal.status = "approved"
        proposal.reviewed_by = reviewer
        proposal.review_notes = notes
        proposal.reviewed_at = datetime.now(timezone.utc)
        proposal.guard_approved_by = reviewer
        proposal.guard_approved_at = datetime.now(timezone.utc)
        proposal.guard_confirmed = guard_confirmed
        self._log_decision(proposal, "approved", reviewer, notes)
        proposal.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return proposal

    async def convert_to_goal(
        self,
        proposal_id: str,
        db: AsyncSession,
    ) -> tuple[ImprovementProposal, Goal]:
        proposal = await self._get_proposal(proposal_id, db)
        self._validate_transition(proposal.status, "converted_to_goal")

        # Create improvement goal
        goal = Goal(
            project_id=proposal.project_id,
            title=f"[Improvement] {proposal.title}",
            description=proposal.suggested_solution,
            status="planned",
            type="improvement",
            source="research",
            source_goal_id=proposal.source_goal_id,
            target_description=proposal.expected_impact,
        )
        db.add(goal)
        await db.flush()

        # Create implementation tasks via CoordinationService
        from app.services.coordination_service import CoordinationService
        parent_task = Task(
            project_id=proposal.project_id,
            content=f"Implement: {proposal.title}",
            status="completed",  # Immediately mark as completed so subtasks spawn
            goal_id=goal.id,
        )
        db.add(parent_task)
        await db.flush()

        service = CoordinationService()
        await service.create_coordinated_subtasks(parent_task, db)

        # Link proposal to goal
        proposal.implementation_goal_id = goal.id
        proposal.status = "converted_to_goal"
        proposal.updated_at = datetime.now(timezone.utc)
        self._log_decision(proposal, "converted_to_goal")

        # Log activity
        db.add(ActivityLog(
            project_id=proposal.project_id,
            action="proposal_converted",
            details=f"Proposal '{proposal.title}' converted to improvement goal",
        ))

        await db.flush()
        return proposal, goal

    async def reject_proposal(
        self,
        proposal_id: str,
        reviewer: str = "user",
        reason: str | None = None,
        db: AsyncSession | None = None,
    ) -> ImprovementProposal:
        if db is None:
            raise ValueError("Database session required")
        proposal = await self._get_proposal(proposal_id, db)
        self._validate_transition(proposal.status, "rejected")
        proposal.status = "rejected"
        proposal.reviewed_by = reviewer
        proposal.review_notes = reason
        self._log_decision(proposal, "rejected", reviewer, reason)
        proposal.reviewed_at = datetime.now(timezone.utc)
        proposal.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return proposal

    async def archive_proposal(
        self, proposal_id: str, db: AsyncSession,
    ) -> ImprovementProposal:
        proposal = await self._get_proposal(proposal_id, db)
        self._validate_transition(proposal.status, "archived")
        proposal.status = "archived"
        self._log_decision(proposal, "archived")
        proposal.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return proposal

    async def get_project_proposals(
        self,
        project_id: str,
        status: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[ImprovementProposal]:
        if db is None:
            return []
        query = select(ImprovementProposal).where(
            ImprovementProposal.project_id == project_id,
        ).order_by(ImprovementProposal.created_at.desc())
        if status:
            query = query.where(ImprovementProposal.status == status)
        result = await db.execute(query)
        return list(result.scalars().all())

    def _log_decision(
        self, proposal: ImprovementProposal, action: str,
        reviewer: str | None = None, reason: str | None = None,
    ) -> None:
        log = json.loads(proposal.decision_log or "[]")
        log.append({
            "action": action,
            "reviewer": reviewer,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        proposal.decision_log = json.dumps(log)

    async def _get_proposal(self, proposal_id: str, db: AsyncSession) -> ImprovementProposal:
        result = await db.execute(
            select(ImprovementProposal).where(ImprovementProposal.id == proposal_id)
        )
        proposal = result.scalars().first()
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")
        return proposal
