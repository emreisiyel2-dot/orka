"""Converts analysis findings into structured ImprovementProposals.

Phase 5: Upgraded with finding deduplication/fusion and score-aware prioritization.
- Findings sharing the same agent + root cause merge into a single richer proposal
- Prioritization uses severity * confidence * impact, not just severity * count
"""

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImprovementProposal, Run
from app.services.research_analyzer import AnalysisFinding, _severity_rank


_SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}


class ProposalGenerator:

    async def generate_from_analysis(
        self,
        project_id: str,
        findings: list[AnalysisFinding],
        source_goal_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[ImprovementProposal]:
        deduped = self._deduplicate_findings(findings)
        prioritized = self._prioritize_findings(deduped)
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

    # ── Deduplication / Fusion ──

    def _deduplicate_findings(self, findings: list[AnalysisFinding]) -> list[AnalysisFinding]:
        """Merge findings that share the same agent + root cause."""
        groups: dict[str, list[AnalysisFinding]] = {}
        ungrouped: list[AnalysisFinding] = []

        for f in findings:
            key = self._fusion_key(f)
            if key:
                groups.setdefault(key, []).append(f)
            else:
                ungrouped.append(f)

        merged: list[AnalysisFinding] = []
        for key, group in groups.items():
            if len(group) <= 1:
                merged.extend(group)
                continue
            primary = group[0]
            for other in group[1:]:
                primary = self._merge_two(primary, other)
            merged.append(primary)

        return merged + ungrouped

    def _fusion_key(self, f: AnalysisFinding) -> str | None:
        """Group by agent_type + root_cause_tag — same root cause for same agent = same problem."""
        if f.related_agent_type and f.root_cause_tag:
            return f"{f.related_agent_type}:{f.root_cause_tag}"
        return None

    def _merge_two(self, a: AnalysisFinding, b: AnalysisFinding) -> AnalysisFinding:
        """Merge two findings into one richer finding."""
        # Keep the more specific type (failure_pattern > performance_degradation)
        if a.finding_type == "failure_pattern":
            primary, secondary = a, b
        elif b.finding_type == "failure_pattern":
            primary, secondary = b, a
        else:
            primary, secondary = a, b

        # Combine evidence
        primary.evidence = primary.evidence + secondary.evidence
        primary.related_run_ids = list(set(primary.related_run_ids + secondary.related_run_ids))
        primary.related_task_ids = list(set(primary.related_task_ids + secondary.related_task_ids))
        primary.related_goal_ids = list(set(primary.related_goal_ids + secondary.related_goal_ids))

        # Use the more specific suggestion
        if len(secondary.suggested_fix) > len(primary.suggested_fix):
            primary.suggested_fix = secondary.suggested_fix

        # Combine descriptions
        primary.description = f"{primary.description} (also: {secondary.description})"

        # Use higher severity
        if _severity_rank(secondary.severity) > _severity_rank(primary.severity):
            primary.severity = secondary.severity

        # Merge scores: average confidence/quality, max impact
        primary.confidence_score = round((a.confidence_score + b.confidence_score) / 2, 2)
        primary.impact_score = round(max(a.impact_score, b.impact_score), 2)
        primary.data_quality_score = round((a.data_quality_score + b.data_quality_score) / 2, 2)

        # Merge affected agents
        primary.affected_agents = list(set(primary.affected_agents + secondary.affected_agents))

        # Merge context_data
        primary.context_data.update(secondary.context_data)

        return primary

    # ── Prioritization ──

    def _prioritize_findings(self, findings: list[AnalysisFinding]) -> list[AnalysisFinding]:
        def score(f: AnalysisFinding) -> float:
            severity_w = _SEVERITY_WEIGHT.get(f.severity, 1)
            confidence_w = f.confidence_score or 0.5
            impact_w = f.impact_score or 0.5
            count = len(f.related_run_ids) or 1
            return severity_w * confidence_w * impact_w * count
        return sorted(findings, key=score, reverse=True)

    # ── Evidence ──

    def _build_evidence_summary(self, finding: AnalysisFinding) -> str:
        parts = [f"{finding.finding_type}: {finding.description}"]
        if finding.evidence:
            for i, e in enumerate(finding.evidence[:3]):
                err = e.get("error", "no details")
                parts.append(f"  [{i+1}] {err[:120]}")
        if finding.related_run_ids:
            parts.append(f"Evidence spans {len(finding.related_run_ids)} runs")
        if finding.confidence_score:
            parts.append(
                f"Confidence: {finding.confidence_score:.0%} | "
                f"Impact: {finding.impact_score:.0%} | "
                f"Data quality: {finding.data_quality_score:.0%}"
            )
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
