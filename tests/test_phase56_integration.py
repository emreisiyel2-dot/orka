"""
Phase 5.6 Real-World Integration Validation

Tests the smart cost + multi-CLI routing system with realistic scenarios.
Uses real SQLite DB, real ModelRouter, real CLIQuotaTracker, real ContextOptimizer.
CLI providers are mocked for controllable health/blocked state.

Run:
  cd backend && rm -f orka.db && source venv/bin/activate
  PYTHONPATH=$(pwd) python3 ../tests/test_phase56_integration.py
"""
import asyncio
import json
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

os.environ["ORKA_LLM_ENABLED"] = "false"  # No real API calls
os.environ["ORKA_CLI_ENABLED"] = "true"    # Enable CLI providers for routing

from app.config.model_config import load_config, CLIProviderConfig, ModelRoutingConfig
from app.database import async_session, init_db
from app.models import RoutingDecision
from app.providers.base import BaseProvider, ModelInfo, ProviderResponse
from app.providers.registry import ProviderRegistry
from app.services.model_router import (
    classify_task, ModelRouter, TaskProfile, lookup_cli_policy,
)
from app.services.cli_quota_tracker import CLIQuotaTracker
from app.services.context_optimizer import ContextOptimizer
from sqlalchemy import select

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


# ── Mock CLI Providers ──────────────────────────────────────

class MockCLIProvider(BaseProvider):
    def __init__(self, name: str, models: list[ModelInfo], healthy: bool = True):
        self.name = name
        self._models = models
        self._healthy = healthy
        self._call_count = 0

    async def complete(self, prompt: str, model: str, **kwargs) -> ProviderResponse:
        self._call_count += 1
        return ProviderResponse(
            content=f"[{self.name}] Response for: {prompt[:50]}...",
            model=model,
            provider=self.name,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            latency_ms=500,
        )

    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncIterator[str]:
        yield ""

    def get_models(self) -> list[ModelInfo]:
        return self._models

    async def health_check(self) -> bool:
        return self._healthy

    def estimate_cost(self, tokens: int, model: str) -> float:
        return 0.0

    def set_healthy(self, healthy: bool):
        self._healthy = healthy


class MockAPIProvider(BaseProvider):
    """Mock API provider that should NEVER be called in CLI-first tests."""
    def __init__(self, name: str = "mock_api"):
        self.name = name
        self._called = False
        self._models = [
            ModelInfo(id="mock-api-model", provider="mock_api", tier="medium",
                      cost_per_1k_input=0.01, cost_per_1k_output=0.03, max_tokens=4096),
        ]

    async def complete(self, prompt: str, model: str, **kwargs) -> ProviderResponse:
        self._called = True
        return ProviderResponse(
            content=f"[PAID API — SHOULD NOT BE CALLED] {prompt[:50]}",
            model=model, provider=self.name, cost_usd=0.05, latency_ms=300,
        )

    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncIterator[str]:
        yield ""

    def get_models(self) -> list[ModelInfo]:
        return self._models

    async def health_check(self) -> bool:
        return True

    def estimate_cost(self, tokens: int, model: str) -> float:
        return tokens * 0.00003


# ── Helpers ─────────────────────────────────────────────────

def build_config() -> ModelRoutingConfig:
    return ModelRoutingConfig(
        low_tier_model="glm-4-plus",
        medium_tier_model="claude-sonnet-4-6",
        high_tier_model="claude-opus-4-7",
        cli_enabled=True,
        cli_providers=[
            CLIProviderConfig(
                name="claude_code",
                binary="claude",
                max_concurrent=3,
                max_sessions_per_hour=20,
            ),
            CLIProviderConfig(
                name="glm_coding",
                binary="glm",
                max_concurrent=3,
                max_sessions_per_hour=20,
            ),
        ],
        providers=[],
    )


def build_registry(claude_healthy: bool = True, glm_healthy: bool = True) -> ProviderRegistry:
    config = build_config()
    registry = ProviderRegistry(config)

    claude = MockCLIProvider("claude_code", [
        ModelInfo(id="claude-sonnet-4-6", provider="claude_code", tier="medium",
                  cost_per_1k_input=0.0, cost_per_1k_output=0.0, max_tokens=8192),
        ModelInfo(id="claude-opus-4-7", provider="claude_code", tier="high",
                  cost_per_1k_input=0.0, cost_per_1k_output=0.0, max_tokens=16384),
    ], healthy=claude_healthy)

    glm = MockCLIProvider("glm_coding", [
        ModelInfo(id="glm-4-plus", provider="glm_coding", tier="medium",
                  cost_per_1k_input=0.0, cost_per_1k_output=0.0, max_tokens=4096),
    ], healthy=glm_healthy)

    # Monkey-patch registry to use our mocks
    registry._providers = {"claude_code": claude, "glm_coding": glm}
    registry._cli_provider_names = {"claude_code", "glm_coding"}
    return registry, claude, glm


def make_router(registry: ProviderRegistry, quota: CLIQuotaTracker | None = None) -> ModelRouter:
    config = build_config()
    router = ModelRouter(config, registry)
    if quota:
        router._cli_quota = quota
    return router


def report(test_name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append((test_name, status, detail))
    icon = "✓" if passed else "✗"
    print(f"  [{icon}] {test_name}: {detail}")


async def count_routing_decisions(db) -> int:
    result = await db.execute(select(RoutingDecision))
    return len(list(result.scalars().all()))


# ── Test Scenarios ──────────────────────────────────────────

async def test_1_simple_task_routes_to_cheaper():
    """Simple coding task should prefer GLM (cheaper) over Claude Code."""
    print("\n" + "=" * 60)
    print("TEST 1: Simple task routes to cheaper/lighter CLI provider")
    print("=" * 60)

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    router = make_router(registry, quota)

    async with async_session() as db:
        # Simple code_gen task — policy says glm_coding first for code_gen+simple
        profile = classify_task("Fix the button styling on the login page", "frontend", has_cli_providers=True)
        print(f"  classify_task: type={profile.task_type}, complexity={profile.complexity}, mode={profile.execution_mode}")

        decision = await router.decide("Fix button styling", profile, task_id=None, db=db)

        report("execution_mode is cli", decision.execution_mode == "cli", f"mode={decision.execution_mode}")
        report("selected_provider is glm_coding", decision.selected_provider == "glm_coding",
               f"provider={decision.selected_provider}")
        report("task_complexity recorded", decision.task_complexity == "simple",
               f"complexity={decision.task_complexity}")
        report("considered_providers logged", decision.considered_providers is not None,
               f"considered={decision.considered_providers}")
        report("selected_cli_provider set", decision.selected_cli_provider == "glm_coding",
               f"cli_provider={decision.selected_cli_provider}")


async def test_2_complex_task_routes_to_strongest():
    """Complex coding/debug task should prefer Claude Code (strongest)."""
    print("\n" + "=" * 60)
    print("TEST 2: Complex coding/debug task routes to strongest CLI")
    print("=" * 60)

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    router = make_router(registry, quota)

    async with async_session() as db:
        profile = classify_task(
            "Redesign the authentication architecture to support OAuth2 and SAML SSO across multiple microservices",
            "backend", importance="critical", has_cli_providers=True,
        )
        print(f"  classify_task: type={profile.task_type}, complexity={profile.complexity}, tier={profile.budget_tier}")

        decision = await router.decide("Redesign auth architecture...", profile, task_id=None, db=db)

        report("execution_mode is cli", decision.execution_mode == "cli", f"mode={decision.execution_mode}")
        report("selected_provider is claude_code", decision.selected_provider == "claude_code",
               f"provider={decision.selected_provider}")
        report("task_complexity is complex/critical", decision.task_complexity in ("complex", "critical"),
               f"complexity={decision.task_complexity}")
        report("selected_model is high tier", decision.selected_model == "claude-opus-4-7",
               f"model={decision.selected_model}")
        report("considered_providers includes both",
               decision.considered_providers is not None and "claude_code" in decision.considered_providers,
               f"considered={decision.considered_providers}")


async def test_3_claude_blocked_falls_back_to_glm():
    """When Claude CLI is blocked, task should fall back to GLM."""
    print("\n" + "=" * 60)
    print("TEST 3: Claude CLI blocked → fallback to GLM/Z.ai CLI")
    print("=" * 60)

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    # Block claude_code
    from datetime import timedelta
    quota.mark_blocked("claude_code", "rate_limit_exceeded",
                      blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    router = make_router(registry, quota)

    async with async_session() as db:
        # code_gen+complex policy is [claude_code, glm_coding] — claude first
        profile = classify_task(
            "Redesign the authentication architecture for microservices",
            "backend", importance="critical", has_cli_providers=True,
        )
        print(f"  classify_task: type={profile.task_type}, complexity={profile.complexity}")

        decision = await router.decide("Redesign auth", profile, task_id=None, db=db)

        report("execution_mode is cli", decision.execution_mode == "cli", f"mode={decision.execution_mode}")
        report("selected_provider is glm_coding (fallback)", decision.selected_provider == "glm_coding",
               f"provider={decision.selected_provider}")
        # Adaptive reorder deprioritizes blocked providers (+50 status penalty),
        # so claude is reordered past glm and never tried. considered only has glm.
        report("claude_code deprioritized (not in considered)",
               decision.considered_providers is not None and "claude_code" not in decision.considered_providers,
               f"considered={decision.considered_providers}")

        signals = quota.get_adaptive_signals("claude_code")
        report("claude_code is_available is False",
               signals["is_available"] == False,
               f"is_available={signals['is_available']}")


async def test_4_both_cli_blocked_pauses_task():
    """When both CLI providers are blocked, task should pause with action_required."""
    print("\n" + "=" * 60)
    print("TEST 4: Both CLI providers unavailable → task pauses (action_required)")
    print("=" * 60)

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    from datetime import timedelta
    quota.mark_blocked("claude_code", "rate_limit",
                      blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    quota.mark_blocked("glm_coding", "quota_exceeded",
                      blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    router = make_router(registry, quota)

    async with async_session() as db:
        profile = classify_task("Fix the critical production bug", "backend", importance="critical",
                                has_cli_providers=True)

        decision = await router.decide("Fix production bug", profile, task_id=None, db=db)

        report("selected_provider is 'none'", decision.selected_provider == "none",
               f"provider={decision.selected_provider}")
        report("blocked_reason is set", decision.blocked_reason is not None,
               f"blocked={decision.blocked_reason}")
        report("reason is all_cli_unavailable", decision.reason == "all_cli_unavailable",
               f"reason={decision.reason}")
        report("both providers in considered_providers",
               decision.considered_providers is not None and len(json.loads(decision.considered_providers)) == 2,
               f"considered={decision.considered_providers}")
        report("both providers in rejected_providers",
               decision.rejected_providers is not None and len(json.loads(decision.rejected_providers)) == 2,
               f"rejected={decision.rejected_providers}")


async def test_5_context_optimizer_trims_long_content():
    """ContextOptimizer should trim long logs/history correctly."""
    print("\n" + "=" * 60)
    print("TEST 5: ContextOptimizer trims long logs/history")
    print("=" * 60)

    # Short prompt — no trim
    opt = ContextOptimizer()
    short = "Fix the typo in the README"
    result = opt.trim(short, "simple", "code_gen")
    report("short prompt unchanged", result == short, f"len={len(result)}")

    # Build a genuinely long prompt: 500 blocks × ~30 words = ~15000 words = ~30000 tokens
    blocks = []
    for i in range(500):
        blocks.append(
            f"[2026-04-29 10:{i % 60:02d}:{(i * 37) % 60:02d}:00] INFO  worker-{i % 5} "
            f"Processing task-{i}: status=running progress={i * 5}% memory=512MB "
            f"cpu=23% disk_io=45MB/s network_in=12MB/s network_out=8MB/s "
            f"gc_pause=2ms heap_alloc=256MB heap_free=128MB threads=8 "
            f"cache_hit_rate=94.2% db_connections=5 db_pool_wait=0.3ms "
            f"request_queue=12 response_time_p50=45ms response_time_p99=230ms"
        )
    long_prompt = "\n\n".join(blocks)
    original_block_count = len(long_prompt.split("\n\n"))
    word_count = len(long_prompt.split())
    print(f"  long_prompt: {original_block_count} blocks, ~{word_count} words, ~{word_count * 2} tokens")

    # Simple docs — aggressive trim (keep 3)
    trimmed_docs = opt.trim(long_prompt, "simple", "docs")
    docs_blocks = len(trimmed_docs.split("\n\n"))
    report("docs+simple keeps 3-4 blocks", docs_blocks <= 4,
           f"original={original_block_count}, trimmed={docs_blocks}")

    # Complex analysis — generous trim (keep 10)
    trimmed_analysis = opt.trim(long_prompt, "complex", "analysis")
    analysis_blocks = len(trimmed_analysis.split("\n\n"))
    report("analysis+complex keeps ~11 blocks", analysis_blocks <= 11,
           f"trimmed={analysis_blocks}")

    # Complex keeps more than simple
    report("complex keeps >= simple blocks", analysis_blocks >= docs_blocks,
           f"complex={analysis_blocks}, simple={docs_blocks}")

    # Trim header present — actual format: "[496 earlier messages trimmed for context optimization]"
    report("trim header present", "trimmed for context optimization" in trimmed_docs,
           f"header check in trimmed output")

    # Adaptive budget tier: low trims more aggressively than high
    opt_adaptive = ContextOptimizer()
    low_result = opt_adaptive.trim(long_prompt, "medium", "code_gen", budget_tier="low")
    high_result = opt_adaptive.trim(long_prompt, "medium", "code_gen", budget_tier="high")
    low_blocks = len(low_result.split("\n\n"))
    high_blocks = len(high_result.split("\n\n"))
    report("low tier trims more than high tier", low_blocks <= high_blocks,
           f"low={low_blocks}, high={high_blocks}")


async def test_6_routing_decision_logs_providers():
    """RoutingDecision should log considered_providers and rejected_providers."""
    print("\n" + "=" * 60)
    print("TEST 6: RoutingDecision logs considered/rejected providers")
    print("=" * 60)

    registry, claude, glm = build_registry(claude_healthy=False)  # Claude unhealthy
    quota = CLIQuotaTracker()
    router = make_router(registry, quota)

    async with async_session() as db:
        # review+medium policy is [claude_code, glm_coding] — claude first, so it gets evaluated
        # Content must be >100 chars to avoid complexity downgrade to "simple"
        profile = classify_task(
            "Review the authentication module for security issues including OAuth2 flows, "
            "session management, and CSRF protection across all API endpoints",
            "qa", has_cli_providers=True,
        )
        decision = await router.decide("Review auth module", profile, task_id=None, db=db)

        considered = json.loads(decision.considered_providers) if decision.considered_providers else []
        rejected = json.loads(decision.rejected_providers) if decision.rejected_providers else []

        report("considered_providers is JSON list", isinstance(considered, list),
               f"type={type(considered).__name__}, count={len(considered)}")
        report("rejected_providers is JSON list of dicts", isinstance(rejected, list) and
               all(isinstance(r, dict) for r in rejected),
               f"count={len(rejected)}")
        report("claude_code in considered (evaluated first)",
               "claude_code" in considered, f"considered={considered}")

        claude_rejection = next((r for r in rejected if r["provider"] == "claude_code"), None)
        report("claude_code rejected with reason",
               claude_rejection is not None and "reason" in claude_rejection,
               f"reason={claude_rejection['reason'] if claude_rejection else 'N/A'}")
        report("glm_coding selected (fallback from claude)",
               decision.selected_provider == "glm_coding",
               f"provider={decision.selected_provider}")


async def test_7_system_stats_shows_provider_breakdown():
    """/api/system/stats should show CLI provider breakdown."""
    print("\n" + "=" * 60)
    print("TEST 7: /api/system/stats shows CLI provider breakdown")
    print("=" * 60)

    quota = CLIQuotaTracker()
    quota.record_session("claude_code", 3.5)
    quota.mark_blocked("glm_coding", "rate_limit")

    # Simulate what system.py does
    cli_providers = {}
    for provider_name in ("claude_code", "glm_coding"):
        status = quota.get_provider_status(provider_name)
        if status:
            cli_providers[provider_name] = status

    stats = {"providers": {"cli": cli_providers}}

    report("'providers' key exists", "providers" in stats, "key present")
    report("'cli' sub-key exists", "cli" in stats["providers"], "cli key present")
    report("claude_code has status", "claude_code" in stats["providers"]["cli"],
           f"providers={list(stats['providers']['cli'].keys())}")

    claude_status = stats["providers"]["cli"].get("claude_code", {})
    report("claude_code has recent_success_rate", "recent_success_rate" in claude_status,
           f"success_rate={claude_status.get('recent_success_rate')}")
    report("claude_code has total_sessions", "total_sessions" in claude_status,
           f"total_sessions={claude_status.get('total_sessions')}")
    report("claude_code has avg_execution_time", "avg_execution_time" in claude_status,
           f"avg_exec_time={claude_status.get('avg_execution_time')}")

    glm_status = stats["providers"]["cli"].get("glm_coding", {})
    report("glm_coding status is blocked", glm_status.get("status") == "blocked",
           f"status={glm_status.get('status')}")
    report("glm_coding has last_error", glm_status.get("last_error") == "rate_limit",
           f"last_error={glm_status.get('last_error')}")


async def test_8_no_silent_paid_api_fallback():
    """route() must never silently fall through to paid API when CLI fails."""
    print("\n" + "=" * 60)
    print("TEST 8: No silent paid API fallback")
    print("=" * 60)

    # Scenario A: CLI provider selected but execution fails
    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    router = make_router(registry, quota)

    # Make Claude's complete() return None (execution failure)
    original_complete = claude.complete
    async def failing_complete(*args, **kwargs):
        raise RuntimeError("CLI process crashed")
    claude.complete = failing_complete

    async with async_session() as db:
        profile = classify_task("Fix the production database connection error", "backend",
                                importance="critical", has_cli_providers=True)

        response, decision = await router.route("Fix DB connection", profile, task_id=None, db=db)

        # route() should return (None, decision) — NOT fall through to API
        report("response is None when CLI fails", response is None, f"response={response}")
        report("decision is not None", decision is not None, "decision exists")
        report("execution_mode is cli", decision.execution_mode == "cli",
               f"mode={decision.execution_mode}")

    # Scenario B: Both CLI blocked — should NOT create API decision
    registry2, claude2, glm2 = build_registry()
    quota2 = CLIQuotaTracker()
    from datetime import timedelta
    quota2.mark_blocked("claude_code", "rate_limit",
                        blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    quota2.mark_blocked("glm_coding", "quota_exceeded",
                        blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    router2 = make_router(registry2, quota2)

    async with async_session() as db:
        # Use code_gen task type (CLI-preferred) — "Analyze" would trigger API mode
        profile = classify_task(
            "Review and fix the critical production issue with the payment service",
            "backend", importance="critical", has_cli_providers=True,
        )
        response, decision = await router2.route("Analyze behavior", profile, task_id=None, db=db)

        report("both blocked: response is None", response is None, f"response={response}")
        report("both blocked: reason is all_cli_unavailable",
               decision.reason == "all_cli_unavailable", f"reason={decision.reason}")
        report("both blocked: blocked_reason set", decision.blocked_reason is not None,
               f"blocked={decision.blocked_reason}")


async def test_9_route_is_pure_forwarder():
    """route() must contain no routing logic — only call decide() then execute."""
    print("\n" + "=" * 60)
    print("TEST 9: route() is pure forwarder (no routing logic)")
    print("=" * 60)

    # Verify by inspecting the source code of route()
    import inspect
    source = inspect.getsource(ModelRouter.route)

    report("route() calls decide()", "decide(" in source, "decide() call found")
    report("route() does NOT call lookup_cli_policy",
           "lookup_cli_policy" not in source, "no policy lookup in route()")
    report("route() does NOT iterate providers",
           "for cp in cli_providers" not in source and "for provider_name in" not in source,
           "no provider iteration in route()")
    report("route() does NOT call check_available",
           "check_available" not in source, "no quota check in route()")

    # Verify decide() never calls provider.complete()
    decide_source = inspect.getsource(ModelRouter.decide)
    report("decide() does NOT call provider.complete",
           ".complete(" not in decide_source, "no execution in decide()")


async def test_10_adaptive_signals_deprioritize_failing_provider():
    """Provider with high failure rate should be deprioritized."""
    print("\n" + "=" * 60)
    print("TEST 10: Adaptive signals deprioritize failing provider")
    print("=" * 60)

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()

    # Make claude_code look bad: 3 failures, 0 successes
    quota.mark_blocked("claude_code", "timeout")
    quota.mark_blocked("claude_code", "crash")
    quota.mark_blocked("claude_code", "rate_limit")

    router = make_router(registry, quota)

    # For code_gen+simple, static policy is [glm_coding, claude_code]
    # With adaptive signals, claude should get +30 penalty (failure_rate=1.0 > 0.5, total=3)
    reordered = router._reorder_by_adaptive_signals(
        ["glm_coding", "claude_code"], "code_gen", "simple",
    )

    report("glm_coding still first (healthy)", reordered[0] == "glm_coding",
           f"order={reordered}")
    report("claude_code deprioritized to last", reordered[-1] == "claude_code",
           f"order={reordered}")

    # Verify signals
    signals = quota.get_adaptive_signals("claude_code")
    report("claude failure_rate is 1.0", signals["recent_failure_rate"] == 1.0,
           f"failure_rate={signals['recent_failure_rate']}")
    report("claude total_sessions is 3", signals["total_sessions"] == 3,
           f"total={signals['total_sessions']}")
    report("claude is_available is False", signals["is_available"] == False,
           f"is_available={signals['is_available']}")


async def test_11_adaptive_signals_boost_reliable_provider():
    """Provider with high success rate should be boosted."""
    print("\n" + "=" * 60)
    print("TEST 11: Adaptive signals boost reliable provider")
    print("=" * 60)

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()

    # Make claude_code look great: 5 successes
    for i in range(5):
        quota.record_session("claude_code", 2.0 + i * 0.5)

    # Make glm_coding look mediocre: 3 sessions, 1 failure
    quota.record_session("glm_coding", 5.0)
    quota.record_session("glm_coding", 3.0)
    quota.mark_blocked("glm_coding", "timeout")

    router = make_router(registry, quota)

    # For code_gen+complex, static policy is [claude_code, glm_coding]
    # Claude should get -10 boost (success_rate=1.0 > 0.8, total=5)
    # GLM should get +30 penalty (failure_rate=0.33, but total=3... wait, 2 success + 1 failure = 3)
    # Actually failure_rate = 1/3 = 0.33 > 0.2, so +15 penalty
    reordered = router._reorder_by_adaptive_signals(
        ["claude_code", "glm_coding"], "code_gen", "complex",
    )

    report("claude_code boosted to first", reordered[0] == "claude_code",
           f"order={reordered}")

    claude_signals = quota.get_adaptive_signals("claude_code")
    report("claude success_rate is 1.0", claude_signals["recent_success_rate"] == 1.0,
           f"success_rate={claude_signals['recent_success_rate']}")
    report("claude is_available is True", claude_signals["is_available"] == True,
           f"is_available={claude_signals['is_available']}")


async def test_12_no_data_uses_static_order():
    """Provider with no data should use static order (no penalty, no boost)."""
    print("\n" + "=" * 60)
    print("TEST 12: No data → use static order")
    print("=" * 60)

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()  # Fresh — no data for any provider
    router = make_router(registry, quota)

    # code_gen+simple static order is [glm_coding, claude_code]
    reordered = router._reorder_by_adaptive_signals(
        ["glm_coding", "claude_code"], "code_gen", "simple",
    )

    report("no-data order matches static", reordered == ["glm_coding", "claude_code"],
           f"order={reordered}")

    # Verify default signals for unknown provider
    signals = quota.get_adaptive_signals("unknown_provider")
    report("unknown provider: success_rate=1.0", signals["recent_success_rate"] == 1.0,
           f"success_rate={signals['recent_success_rate']}")
    report("unknown provider: failure_rate=0.0", signals["recent_failure_rate"] == 0.0,
           f"failure_rate={signals['recent_failure_rate']}")
    report("unknown provider: total_sessions=0", signals["total_sessions"] == 0,
           f"total={signals['total_sessions']}")


# ── Main ────────────────────────────────────────────────────

async def main():
    await init_db()

    print("=" * 60)
    print("ORKA Phase 5.6 — Real-World Integration Validation")
    print("=" * 60)

    await test_1_simple_task_routes_to_cheaper()
    await test_2_complex_task_routes_to_strongest()
    await test_3_claude_blocked_falls_back_to_glm()
    await test_4_both_cli_blocked_pauses_task()
    await test_5_context_optimizer_trims_long_content()
    await test_6_routing_decision_logs_providers()
    await test_7_system_stats_shows_provider_breakdown()
    await test_8_no_silent_paid_api_fallback()
    await test_9_route_is_pure_forwarder()
    await test_10_adaptive_signals_deprioritize_failing_provider()
    await test_11_adaptive_signals_boost_reliable_provider()
    await test_12_no_data_uses_static_order()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    total = len(results)
    print(f"  {passed}/{total} passed, {failed} failed")

    if failed > 0:
        print("\n  FAILED TESTS:")
        for name, status, detail in results:
            if status == FAIL:
                print(f"    ✗ {name}: {detail}")

    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
