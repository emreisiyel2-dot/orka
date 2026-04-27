"""Analysis engine — scans Runs, failures, and performance data for improvement opportunities.

Phase 5: Upgraded from template-based pattern detection to context-aware intelligent reasoning.
- Minimum sample thresholds to prevent noise
- Exponential severity with same-task and consecutive boosts
- Context-aware suggestions with specific numbers
- Root cause classification for intelligent grouping
- Insight scoring (confidence, impact, data quality)
- Expanded cost analysis (mixed mode, inefficient routing)
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Run, Task, Goal


# Minimum sample thresholds — findings below these are noise, not signal
_MIN_RUNS_FAILURE = 3       # failure patterns: need >=3 failed runs
_MIN_RUNS_PERFORMANCE = 5   # performance: need >=5 total runs per agent
_MIN_RUNS_COST = 8          # cost analysis: need >=8 runs total

_DEFAULT_TIMEOUT_LIMIT = 300  # seconds


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
    # Phase 5: Insight scoring
    confidence_score: float = 0.0    # 0.0-1.0: how reliable is this finding?
    impact_score: float = 0.0        # 0.0-1.0: how much improvement possible?
    data_quality_score: float = 0.0   # 0.0-1.0: how much data supports this?
    # Phase 5: Context for intelligent suggestions
    root_cause_tag: str = ""         # e.g., "timeout_too_tight", "quota_limit_reached"
    context_data: dict = field(default_factory=dict)


class ResearchAnalyzer:

    async def analyze_project(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        findings: list[AnalysisFinding] = []
        findings.extend(await self.analyze_failures(project_id, db))
        findings.extend(await self.analyze_performance(project_id, db))
        findings.extend(await self.analyze_costs(project_id, db))
        return sorted(findings, key=lambda f: _severity_rank(f.severity), reverse=True)

    # ── Failure Analysis ──

    async def analyze_failures(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        runs = await self._get_project_runs(project_id, db)
        failed = [r for r in runs if r.status == "failed"]

        if len(failed) < _MIN_RUNS_FAILURE:
            return []

        by_type: dict[str, list[Run]] = {}
        for r in failed:
            key = r.failure_type or "unknown"
            by_type.setdefault(key, []).append(r)

        findings: list[AnalysisFinding] = []
        for ftype, f_runs in by_type.items():
            errors = [r.error_message for r in f_runs[:5] if r.error_message]
            agents = list(set(r.agent_type for r in f_runs))
            run_ids = [r.id for r in f_runs[:10]]
            task_ids = list(set(r.task_id for r in f_runs[:10]))
            goal_ids = list(set(r.goal_id for r in f_runs if r.goal_id))
            providers = list(set(r.provider for r in f_runs if r.provider != "unknown"))
            models = list(set(r.model for r in f_runs if r.model != "unknown"))

            same_task = len(set(r.task_id for r in f_runs)) == 1
            consecutive = self._are_consecutive_failures(f_runs, runs)

            root_cause_tag, context_data = self._classify_root_cause(ftype, f_runs)

            finding = AnalysisFinding(
                finding_type="failure_pattern",
                severity=self._compute_severity(len(f_runs), same_task, consecutive),
                title=self._build_failure_title(ftype, f_runs, agents),
                description=f"{len(f_runs)} runs failed with {ftype} in this project"
                            + (" (all same task)" if same_task else "")
                            + (" — consecutive failures" if consecutive else ""),
                evidence=[{"run_id": r.id, "task_id": r.task_id, "error": r.error_message} for r in f_runs[:5]],
                affected_agents=agents,
                suggested_fix="",  # filled by _generate_contextual_fix below
                expected_impact=f"Could prevent {len(f_runs)} future failures",
                risk_level="medium",
                effort="moderate",
                related_run_ids=run_ids,
                related_goal_ids=goal_ids,
                related_task_ids=task_ids,
                related_agent_type=agents[0] if len(agents) == 1 else None,
                related_provider=providers[0] if len(providers) == 1 else None,
                related_model=models[0] if len(models) == 1 else None,
                confidence_score=self._compute_confidence(f_runs, same_task),
                impact_score=self._compute_impact(len(f_runs), len(runs)),
                data_quality_score=self._compute_data_quality(f_runs),
                root_cause_tag=root_cause_tag,
                context_data=context_data,
            )
            finding.suggested_fix = self._generate_contextual_fix(finding)
            findings.append(finding)

        return findings

    # ── Performance Analysis ──

    async def analyze_performance(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        from app.services.run_manager import RunManager

        perf_data = await RunManager().get_agent_performance(project_id, db=db)
        runs = await self._get_project_runs(project_id, db)
        findings: list[AnalysisFinding] = []

        for agent in perf_data:
            agent_runs = [r for r in runs if r.agent_type == agent.agent_type]

            # Minimum sample threshold
            if len(agent_runs) < _MIN_RUNS_PERFORMANCE:
                continue

            run_ids = [r.id for r in agent_runs[:10]]
            task_ids = list(set(r.task_id for r in agent_runs[:10]))
            goal_ids = list(set(r.goal_id for r in agent_runs if r.goal_id))

            if agent.retry_rate > 0.15:
                retried_runs = [r for r in agent_runs if r.retry_count > 0]
                retried_failures = [r for r in retried_runs if r.status == "failed"]
                root_tag = "retry_pattern__" + (
                    retried_failures[0].failure_type or "unknown"
                    if retried_failures else "unknown"
                )

                finding = AnalysisFinding(
                    finding_type="performance_degradation",
                    severity="high" if agent.retry_rate > 0.3 else "medium",
                    title=f"{agent.agent_type} agent: {agent.retry_rate:.0%} retry rate",
                    description=(
                        f"{agent.agent_type} retried {agent.retry_rate:.0%} of runs "
                        f"({len(retried_runs)}/{len(agent_runs)})"
                    ),
                    evidence=[],
                    affected_agents=[agent.agent_type],
                    suggested_fix=self._build_retry_fix(agent.agent_type, retried_runs),
                    expected_impact=f"Could save {int(agent.total_runs * agent.retry_rate)} retry executions",
                    risk_level="low",
                    effort="simple",
                    related_run_ids=run_ids,
                    related_goal_ids=goal_ids,
                    related_task_ids=task_ids,
                    related_agent_type=agent.agent_type,
                    confidence_score=self._compute_confidence(agent_runs, False),
                    impact_score=self._compute_impact(len(retried_runs), len(agent_runs)),
                    data_quality_score=self._compute_data_quality(agent_runs),
                    root_cause_tag=root_tag,
                    context_data={
                        "retry_rate": agent.retry_rate,
                        "retried_count": len(retried_runs),
                        "total_runs": len(agent_runs),
                    },
                )
                findings.append(finding)

            if agent.avg_duration_seconds > 30:
                slow_runs = [r for r in agent_runs if r.duration_seconds and r.duration_seconds > 30]
                durations = [r.duration_seconds for r in slow_runs if r.duration_seconds]

                finding = AnalysisFinding(
                    finding_type="performance_degradation",
                    severity="medium",
                    title=f"{agent.agent_type} agent: avg {agent.avg_duration_seconds:.1f}s execution",
                    description=(
                        f"Average duration {agent.avg_duration_seconds:.1f}s across "
                        f"{len(agent_runs)} runs ({len(slow_runs)} over 30s)"
                    ),
                    evidence=[],
                    affected_agents=[agent.agent_type],
                    suggested_fix=self._build_slow_fix(
                        agent.agent_type, agent.avg_duration_seconds, durations,
                    ),
                    expected_impact=f"{len(slow_runs)} runs could benefit from optimization",
                    risk_level="medium",
                    effort="complex",
                    related_run_ids=run_ids,
                    related_goal_ids=goal_ids,
                    related_task_ids=task_ids,
                    related_agent_type=agent.agent_type,
                    confidence_score=self._compute_confidence(agent_runs, False),
                    impact_score=self._compute_impact(len(slow_runs), len(agent_runs)),
                    data_quality_score=self._compute_data_quality(agent_runs),
                    root_cause_tag="slow_execution",
                    context_data={
                        "avg_duration": agent.avg_duration_seconds,
                        "max_duration": max(durations) if durations else 0,
                        "slow_count": len(slow_runs),
                    },
                )
                findings.append(finding)

        return findings

    # ── Cost Analysis ──

    async def analyze_costs(
        self, project_id: str, db: AsyncSession,
    ) -> list[AnalysisFinding]:
        runs = await self._get_project_runs(project_id, db)
        if len(runs) < _MIN_RUNS_COST:
            return []

        findings: list[AnalysisFinding] = []
        by_mode: dict[str, list[Run]] = {}
        for r in runs:
            by_mode.setdefault(r.execution_mode, []).append(r)

        api_runs = by_mode.get("api", [])
        cli_runs = by_mode.get("cli", [])

        # Strategy 1: API-only (no CLI configured)
        if len(api_runs) >= 10 and len(cli_runs) == 0:
            findings.append(AnalysisFinding(
                finding_type="cost_optimization",
                severity="low",
                title="All runs use API mode — CLI providers may reduce cost",
                description=f"{len(api_runs)} API runs, 0 CLI runs",
                evidence=[],
                affected_agents=[],
                suggested_fix=(
                    "Configure CLI providers for code_gen and review tasks. "
                    f"Current: {len(api_runs)} paid API runs with no CLI alternative."
                ),
                expected_impact="CLI runs have $0 marginal cost",
                risk_level="low",
                effort="simple",
                related_run_ids=[r.id for r in api_runs[:10]],
                related_task_ids=list(set(r.task_id for r in api_runs[:10])),
                related_goal_ids=list(set(r.goal_id for r in api_runs if r.goal_id)),
                confidence_score=self._compute_confidence(api_runs, False),
                impact_score=0.6,
                data_quality_score=self._compute_data_quality(api_runs),
                root_cause_tag="no_cli_configured",
                context_data={"api_run_count": len(api_runs), "cli_run_count": 0},
            ))

        # Strategy 2: Mixed mode — CLI available but some agents still use API
        if cli_runs and api_runs:
            api_by_agent: dict[str, list[Run]] = {}
            for r in api_runs:
                api_by_agent.setdefault(r.agent_type, []).append(r)
            for agent_type, agent_api in api_by_agent.items():
                if len(agent_api) >= 3:
                    findings.append(AnalysisFinding(
                        finding_type="cost_optimization",
                        severity="medium",
                        title=f"{agent_type} agent uses API ({len(agent_api)}x) despite CLI availability",
                        description=(
                            f"CLI provider available but {agent_type} ran "
                            f"{len(agent_api)} tasks via paid API"
                        ),
                        suggested_fix=(
                            f"Route {agent_type} tasks to CLI provider for $0 marginal cost. "
                            f"CLI runs exist in project, confirming availability."
                        ),
                        expected_impact=f"{len(agent_api)} runs/cycle could shift to free CLI tier",
                        risk_level="low",
                        effort="simple",
                        related_run_ids=[r.id for r in agent_api[:10]],
                        related_task_ids=list(set(r.task_id for r in agent_api[:10])),
                        related_goal_ids=list(set(r.goal_id for r in agent_api if r.goal_id)),
                        affected_agents=[agent_type],
                        related_agent_type=agent_type,
                        confidence_score=self._compute_confidence(agent_api, False),
                        impact_score=self._compute_impact(len(agent_api), len(runs)),
                        data_quality_score=self._compute_data_quality(agent_api),
                        root_cause_tag="api_when_cli_available",
                        context_data={
                            "agent_type": agent_type,
                            "api_count": len(agent_api),
                            "cli_count": len(cli_runs),
                        },
                    ))

        # Strategy 3: High-tier model used for quick (likely simple) tasks
        high_model_runs = [
            r for r in runs
            if any(tier in (r.model or "").lower() for tier in ("opus", "gpt-4"))
        ]
        if len(high_model_runs) >= 3:
            simple_high = [
                r for r in high_model_runs
                if r.duration_seconds and r.duration_seconds < 10
            ]
            if len(simple_high) >= 3:
                models_used = list(set(r.model for r in simple_high))
                findings.append(AnalysisFinding(
                    finding_type="cost_optimization",
                    severity="low",
                    title=f"High-tier model used for {len(simple_high)} quick tasks",
                    description=(
                        f"{len(simple_high)} runs completed in <10s using expensive models "
                        f"({', '.join(models_used)})"
                    ),
                    suggested_fix=(
                        f"Tasks completing in <10s may not need high-tier models. "
                        f"Route quick tasks to {', '.join(models_used)} alternatives for cost savings."
                    ),
                    expected_impact=f"~{len(simple_high)} runs/cycle could use cheaper models",
                    risk_level="low",
                    effort="simple",
                    related_run_ids=[r.id for r in simple_high[:10]],
                    related_task_ids=list(set(r.task_id for r in simple_high[:10])),
                    related_goal_ids=list(set(r.goal_id for r in simple_high if r.goal_id)),
                    affected_agents=list(set(r.agent_type for r in simple_high)),
                    confidence_score=0.5,
                    impact_score=0.3,
                    data_quality_score=self._compute_data_quality(simple_high),
                    root_cause_tag="high_model_for_simple_tasks",
                    context_data={
                        "quick_task_count": len(simple_high),
                        "models": models_used,
                    },
                ))

        return findings

    # ── Helpers ──

    async def _get_project_runs(self, project_id: str, db: AsyncSession) -> list[Run]:
        result = await db.execute(
            select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
        )
        return list(result.scalars().all())

    def _compute_severity(self, failure_count: int, same_task: bool, consecutive: bool) -> str:
        if failure_count >= 7:
            base = "critical"
        elif failure_count >= 4:
            base = "high"
        elif failure_count >= 2:
            base = "medium"
        else:
            base = "low"

        if same_task and base in ("medium", "high"):
            base = {"medium": "high", "high": "critical"}[base]
        if consecutive and base == "medium":
            base = "high"

        return base

    def _are_consecutive_failures(self, failed_runs: list[Run], all_runs: list[Run]) -> bool:
        if len(failed_runs) < 2 or not all_runs:
            return False

        def _safe_ts(r: Run):
            """Normalize created_at for comparison (handle naive vs aware datetimes)."""
            ts = r.created_at
            if ts is None:
                return ""
            if ts.tzinfo is None:
                from datetime import timezone
                ts = ts.replace(tzinfo=timezone.utc)
            return ts

        sorted_fails = sorted(failed_runs, key=_safe_ts, reverse=True)
        latest_overall = max(all_runs, key=_safe_ts)
        return sorted_fails[0].id == latest_overall.id

    def _classify_root_cause(self, failure_type: str, runs: list[Run]) -> tuple[str, dict]:
        ctx: dict = {}

        if failure_type == "timeout":
            durations = [r.duration_seconds for r in runs if r.duration_seconds]
            ctx["durations"] = durations
            ctx["timeout_limit"] = _DEFAULT_TIMEOUT_LIMIT
            ctx["execution_mode"] = runs[0].execution_mode
            ctx["provider"] = runs[0].provider
            ctx["same_task"] = len(set(r.task_id for r in runs)) == 1
            ctx["consecutive"] = True  # set properly by caller
            tag = "timeout_too_tight"

        elif failure_type == "quota_block":
            ctx["provider"] = runs[0].provider
            ctx["execution_mode"] = runs[0].execution_mode
            ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
            tag = "quota_limit_reached"

        elif failure_type == "model_error":
            ctx["model"] = runs[0].model
            ctx["provider"] = runs[0].provider
            ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
            tag = "model_error"

        elif failure_type == "cli_error":
            ctx["provider"] = runs[0].provider
            ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
            tag = "cli_binary_issue"

        elif failure_type == "validation_failed":
            ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
            tag = "validation_gap"

        else:
            ctx["error_messages"] = [r.error_message for r in runs[:3] if r.error_message]
            tag = "unknown_failure"

        return tag, ctx

    def _generate_contextual_fix(self, finding: AnalysisFinding) -> str:
        ctx = finding.context_data
        tag = finding.root_cause_tag

        if tag == "timeout_too_tight":
            durations = ctx.get("durations", [])
            limit = ctx.get("timeout_limit", _DEFAULT_TIMEOUT_LIMIT)
            mode = ctx.get("execution_mode", "unknown")
            if durations:
                max_dur = max(durations)
                suggested = int(max_dur * 1.2)
                return (
                    f"{mode.upper()} subprocess timed out at {max_dur:.0f}s "
                    f"(limit {limit}s). Increase timeout to {suggested}s "
                    f"or decompose into smaller tasks."
                )
            return f"Timeout failures detected (limit {limit}s). Increase timeout or decompose tasks."

        if tag == "quota_limit_reached":
            provider = ctx.get("provider", "unknown")
            errors = ctx.get("error_messages", [])
            err_hint = f" ('{errors[0][:60]}')" if errors else ""
            return (
                f"{provider} quota exhausted{err_hint}. "
                f"Options: (1) increase quota, (2) add API fallback for quota peaks, "
                f"(3) implement request queuing to stay within limits."
            )

        if tag == "model_error":
            model = ctx.get("model", "unknown")
            errors = ctx.get("error_messages", [])
            if errors:
                return (
                    f"{model} returned errors: '{errors[0][:80]}'. "
                    f"Add retry logic with exponential backoff and fallback to "
                    f"a different model tier."
                )
            return f"{model} returned repeated errors. Add retry with fallback model."

        if tag == "cli_binary_issue":
            provider = ctx.get("provider", "unknown")
            errors = ctx.get("error_messages", [])
            err_hint = f" ('{errors[0][:60]}')" if errors else ""
            return (
                f"{provider} CLI binary failed{err_hint}. "
                f"Verify binary is installed and accessible, add health checks before execution."
            )

        if tag == "validation_gap":
            errors = ctx.get("error_messages", [])
            if errors:
                return (
                    f"Validation errors: '{errors[0][:80]}'. "
                    f"Strengthen pre-execution validation to catch these issues before run starts."
                )
            return "Strengthen pre-execution validation to catch issues early."

        return f"Investigate root cause of {finding.finding_type}. Evidence: {finding.description}"

    def _build_failure_title(self, ftype: str, f_runs: list[Run], agents: list[str]) -> str:
        agent_str = ", ".join(agents)
        count = len(f_runs)
        same_task = len(set(r.task_id for r in f_runs)) == 1
        prefix = f"Repeated {ftype} failures"
        if same_task:
            task_id = f_runs[0].task_id[:8]
            prefix = f"Concentrated {ftype} failures on task {task_id}.."
        return f"{prefix} in {agent_str} ({count}x)"

    def _build_retry_fix(self, agent_type: str, retried_runs: list[Run]) -> str:
        failed_retries = [r for r in retried_runs if r.status == "failed"]
        if not failed_retries:
            return (
                f"{agent_type} has high retry rate but retries succeed. "
                f"Add pre-validation to reduce unnecessary retries."
            )
        ftype = failed_retries[0].failure_type or "unknown"
        err = failed_retries[0].error_message or "no details"
        return (
            f"{agent_type} retries often fail with {ftype}: '{err[:80]}'. "
            f"Fix root cause ({ftype}) to eliminate retries entirely."
        )

    def _build_slow_fix(self, agent_type: str, avg: float, durations: list[float]) -> str:
        if not durations:
            return f"{agent_type} averages {avg:.1f}s. Profile slow operations and consider decomposition."
        max_d = max(durations)
        return (
            f"{agent_type} averages {avg:.1f}s (max {max_d:.1f}s). "
            f"Profile operations over 30s, consider task decomposition for runs exceeding 60s."
        )

    def _compute_confidence(self, runs: list[Run], same_task: bool) -> float:
        count = len(runs)
        if count >= 10:
            confidence = 0.95
        elif count >= 5:
            confidence = 0.80
        elif count >= 3:
            confidence = 0.60
        else:
            confidence = 0.30
        if same_task:
            confidence = min(1.0, confidence + 0.10)
        return round(confidence, 2)

    def _compute_impact(self, failure_count: int, total_runs: int) -> float:
        if total_runs == 0:
            return 0.0
        fraction = failure_count / total_runs
        return round(min(0.95, fraction * 1.2 + 0.15), 2)

    def _compute_data_quality(self, runs: list[Run]) -> float:
        if not runs:
            return 0.0
        fields_checked = 0
        fields_populated = 0
        for r in runs[:10]:
            fields_checked += 4
            if r.error_message:
                fields_populated += 1
            if r.duration_seconds is not None:
                fields_populated += 1
            if r.provider and r.provider != "unknown":
                fields_populated += 1
            if r.model and r.model != "unknown":
                fields_populated += 1
        return round(fields_populated / fields_checked, 2) if fields_checked else 0.0


def _severity_rank(severity: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(severity, 0)
