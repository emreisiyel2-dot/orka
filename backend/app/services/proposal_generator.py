"""Converts analysis findings into structured ImprovementProposals."""

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImprovementProposal, Run
from app.services.research_analyzer import AnalysisFinding


_SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}


class ProposalGenerator:

    async def generate_from_analysis(
        self,
        project_id: str,
        findings: list[AnalysisFinding],
        source_goal_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[ImprovementProposal]:
        prioritized = self._prioritize_findings(findings)
        proposals: list[ImprovementProposal] = []

        for finding in prioritized:
            proposal = ImprovementProposal(
                project_id=project_id,
                source_goal_id=source_goal_id,
                title=finding.title[:300],
                status="draft",
                problem_description=finding.description,
                evidence_summary=self._build_evidence_summary(finding),
                suggested_solution=finding.suggested_fix,
                expected_impact=finding.expected_impact,
                risk_level=finding.risk_level,
                implementation_effort=finding.effort,
                analysis_type=finding.finding_type,
                affected_agents=json.dumps(finding.affected_agents),
                affected_areas=json.dumps(self._infer_areas(finding)),
                related_run_ids=json.dumps(finding.related_run_ids),
                related_goal_ids=json.dumps(finding.related_goal_ids),
                related_task_ids=json.dumps(finding.related_task_ids),
                related_agent_type=finding.related_agent_type,
                related_provider=finding.related_provider,
                related_model=finding.related_model,
            )
            if db is not None:
                db.add(proposal)
                await db.flush()
            proposals.append(proposal)

        return proposals

    async def generate_from_goal(
        self,
        goal_id: str,
        db: AsyncSession,
    ) -> list[ImprovementProposal]:
        from app.services.research_analyzer import ResearchAnalyzer

        result = await db.execute(
            select(Run).where(Run.goal_id == goal_id).order_by(Run.created_at.desc())
        )
        runs = list(result.scalars().all())
        if not runs:
            return []

        project_id = runs[0].project_id
        analyzer = ResearchAnalyzer()

        failure_findings = [
            f for f in await analyzer.analyze_failures(project_id, db)
            if goal_id in f.related_goal_ids
        ]
        perf_findings = [
            f for f in await analyzer.analyze_performance(project_id, db)
            if any(r.goal_id == goal_id for r in runs if r.agent_type in f.affected_agents)
        ]

        all_findings = failure_findings + perf_findings
        if not all_findings:
            return []

        return await self.generate_from_analysis(
            project_id=project_id,
            findings=all_findings,
            source_goal_id=goal_id,
            db=db,
        )

    def _prioritize_findings(self, findings: list[AnalysisFinding]) -> list[AnalysisFinding]:
        def score(f: AnalysisFinding) -> float:
            weight = _SEVERITY_WEIGHT.get(f.severity, 1)
            count = len(f.related_run_ids) or 1
            agent_mult = 1 + len(f.affected_agents)
            return weight * count * agent_mult
        return sorted(findings, key=score, reverse=True)

    def _build_evidence_summary(self, finding: AnalysisFinding) -> str:
        parts = [f"{finding.finding_type}: {finding.description}"]
        if finding.evidence:
            for i, e in enumerate(finding.evidence[:3]):
                err = e.get("error", "no details")
                parts.append(f"  [{i+1}] {err[:120]}")
        if finding.related_run_ids:
            parts.append(f"Evidence spans {len(finding.related_run_ids)} runs")
        return "\n".join(parts)

    def _infer_areas(self, finding: AnalysisFinding) -> list[str]:
        areas: list[str] = []
        type_area_map = {
            "failure_pattern": "error handling",
            "performance_degradation": "execution pipeline",
            "cost_optimization": "provider configuration",
        }
        areas.append(type_area_map.get(finding.finding_type, "general"))
        for agent in finding.affected_agents:
            areas.append(f"{agent} agent")
        return list(set(areas))
