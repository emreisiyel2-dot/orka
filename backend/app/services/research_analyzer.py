"""Analysis engine — scans Runs, failures, and performance data for improvement opportunities."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Run, Task, Goal


@dataclass
class AnalysisFinding:
    finding_type: str       # "failure_pattern" | "performance_degradation" | "cost_optimization"
    severity: str           # "low" | "medium" | "high" | "critical"
    title: str
    description: str
    evidence: list[dict] = field(default_factory=list)
    affected_agents: list[str] = field(default_factory=list)
    suggested_fix: str = ""
    expected_impact: str = ""
    risk_level: str = "medium"
    effort: str = "moderate"
    # Evidence linking
    related_run_ids: list[str] = field(default_factory=list)
    related_goal_ids: list[str] = field(default_factory=list)
    related_task_ids: list[str] = field(default_factory=list)
    related_agent_type: str | None = None
    related_provider: str | None = None
    related_model: str | None = None


class ResearchAnalyzer:

    async def analyze_project(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        findings: list[AnalysisFinding] = []
        findings.extend(await self.analyze_failures(project_id, db))
        findings.extend(await self.analyze_performance(project_id, db))
        findings.extend(await self.analyze_costs(project_id, db))
        return sorted(findings, key=lambda f: self._severity_rank(f.severity), reverse=True)

    async def analyze_failures(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        runs = await self._get_project_runs(project_id, db)
        failed = [r for r in runs if r.status == "failed"]

        by_type: dict[str, list[Run]] = {}
        for r in failed:
            key = r.failure_type or "unknown"
            by_type.setdefault(key, []).append(r)

        findings: list[AnalysisFinding] = []
        for ftype, f_runs in by_type.items():
            if len(f_runs) < 3:
                continue
            errors = [r.error_message for r in f_runs[:5] if r.error_message]
            agents = list(set(r.agent_type for r in f_runs))
            run_ids = [r.id for r in f_runs[:10]]
            task_ids = list(set(r.task_id for r in f_runs[:10]))
            goal_ids = list(set(r.goal_id for r in f_runs if r.goal_id))
            providers = list(set(r.provider for r in f_runs if r.provider != "unknown"))
            models = list(set(r.model for r in f_runs if r.model != "unknown"))

            findings.append(AnalysisFinding(
                finding_type="failure_pattern",
                severity=self._severity_from_count(len(f_runs)),
                title=f"Repeated {ftype} failures in {', '.join(agents)}",
                description=f"{len(f_runs)} runs failed with {ftype} in this project",
                evidence=[{"run_id": r.id, "task_id": r.task_id, "error": r.error_message} for r in f_runs[:5]],
                affected_agents=agents,
                suggested_fix=self._suggest_fix(ftype, errors),
                expected_impact=f"Could prevent {len(f_runs)} future failures",
                risk_level="medium",
                effort="moderate",
                related_run_ids=run_ids,
                related_goal_ids=goal_ids,
                related_task_ids=task_ids,
                related_agent_type=agents[0] if len(agents) == 1 else None,
                related_provider=providers[0] if len(providers) == 1 else None,
                related_model=models[0] if len(models) == 1 else None,
            ))
        return findings

    async def analyze_performance(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        from app.services.run_manager import RunManager

        perf_data = await RunManager().get_agent_performance(project_id, db=db)
        runs = await self._get_project_runs(project_id, db)
        findings: list[AnalysisFinding] = []

        for agent in perf_data:
            agent_runs = [r for r in runs if r.agent_type == agent.agent_type]
            run_ids = [r.id for r in agent_runs[:10]]
            task_ids = list(set(r.task_id for r in agent_runs[:10]))
            goal_ids = list(set(r.goal_id for r in agent_runs if r.goal_id))

            if agent.retry_rate > 0.15:
                findings.append(AnalysisFinding(
                    finding_type="performance_degradation",
                    severity="high",
                    title=f"{agent.agent_type} agent: {agent.retry_rate:.0%} retry rate",
                    description=f"{agent.agent_type} retried {agent.retry_rate:.0%} of runs",
                    evidence=[],
                    affected_agents=[agent.agent_type],
                    suggested_fix="Investigate root cause of retries, add pre-validation",
                    expected_impact=f"Could save {int(agent.total_runs * agent.retry_rate)} retry executions",
                    risk_level="low",
                    effort="simple",
                    related_run_ids=run_ids,
                    related_goal_ids=goal_ids,
                    related_task_ids=task_ids,
                    related_agent_type=agent.agent_type,
                ))

            if agent.avg_duration_seconds > 30:
                findings.append(AnalysisFinding(
                    finding_type="performance_degradation",
                    severity="medium",
                    title=f"{agent.agent_type} agent: avg {agent.avg_duration_seconds:.1f}s execution",
                    description="Average duration significantly above baseline",
                    evidence=[],
                    affected_agents=[agent.agent_type],
                    suggested_fix="Profile slow operations, consider task decomposition",
                    expected_impact="50-70% execution time reduction possible",
                    risk_level="medium",
                    effort="complex",
                    related_run_ids=run_ids,
                    related_goal_ids=goal_ids,
                    related_task_ids=task_ids,
                    related_agent_type=agent.agent_type,
                ))
        return findings

    async def analyze_costs(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        runs = await self._get_project_runs(project_id, db)
        by_mode: dict[str, list[Run]] = {}
        for r in runs:
            by_mode.setdefault(r.execution_mode, []).append(r)

        findings: list[AnalysisFinding] = []
        api_runs = by_mode.get("api", [])
        if len(api_runs) > 10 and len(by_mode.get("cli", [])) == 0:
            findings.append(AnalysisFinding(
                finding_type="cost_optimization",
                severity="low",
                title="All runs use API mode — CLI providers may reduce cost",
                description=f"{len(api_runs)} API runs, 0 CLI runs",
                evidence=[],
                affected_agents=[],
                suggested_fix="Configure CLI providers for code_gen and review tasks",
                expected_impact="CLI runs have $0 marginal cost",
                risk_level="low",
                effort="simple",
                related_run_ids=[r.id for r in api_runs[:10]],
                related_task_ids=list(set(r.task_id for r in api_runs[:10])),
                related_goal_ids=list(set(r.goal_id for r in api_runs if r.goal_id)),
            ))
        return findings

    # ── Helpers ──

    async def _get_project_runs(self, project_id: str, db: AsyncSession) -> list[Run]:
        result = await db.execute(
            select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
        )
        return list(result.scalars().all())

    def _severity_from_count(self, count: int) -> str:
        if count >= 10:
            return "critical"
        if count >= 7:
            return "high"
        if count >= 5:
            return "medium"
        return "low"

    def _severity_rank(self, severity: str) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(severity, 0)

    def _suggest_fix(self, failure_type: str, errors: list[str]) -> str:
        fixes = {
            "timeout": "Increase execution timeout or decompose long-running tasks",
            "model_error": "Add retry logic with fallback model selection",
            "cli_error": "Verify CLI binary is installed and accessible, add health checks",
            "quota_block": "Increase quota limits or add API fallback for quota-exhausted scenarios",
            "validation_failed": "Strengthen pre-execution validation to catch issues early",
        }
        return fixes.get(failure_type, "Investigate root cause and add targeted error handling")
