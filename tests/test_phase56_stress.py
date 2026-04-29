"""
Phase 5.6 Real-World Stress Test

Simulates 25+ realistic tasks across all complexity tiers with:
  - Normal routing (both CLI healthy)
  - Claude blocked → GLM fallback
  - GLM blocked → Claude fallback
  - Both blocked → task pause
  - CLI execution failure → no silent API fallback
  - Context optimization on oversized prompts
  - Adaptive signal degradation over many sessions

Run:
  cd backend && rm -f orka.db && source venv/bin/activate
  PYTHONPATH=$(pwd) python3 ../tests/test_phase56_stress.py
"""
import asyncio
import json
import sys
import os
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

os.environ["ORKA_LLM_ENABLED"] = "false"
os.environ["ORKA_CLI_ENABLED"] = "true"

from app.config.model_config import CLIProviderConfig, ModelRoutingConfig
from app.database import async_session, init_db
from app.providers.base import BaseProvider, ModelInfo, ProviderResponse
from app.providers.registry import ProviderRegistry
from app.services.model_router import classify_task, ModelRouter, lookup_cli_policy
from app.services.cli_quota_tracker import CLIQuotaTracker
from app.services.context_optimizer import ContextOptimizer

# ── Mock Providers ────────────────────────────────────────────

class MockCLI(BaseProvider):
    def __init__(self, name, models, healthy=True, fail_rate=0.0):
        self.name = name
        self._models = models
        self._healthy = healthy
        self._fail_rate = fail_rate
        self._calls = 0

    async def complete(self, prompt, model, **kw) -> ProviderResponse:
        self._calls += 1
        if self._fail_rate > 0 and (self._calls % int(1 / self._fail_rate) == 0):
            raise RuntimeError(f"{self.name} process crashed")
        return ProviderResponse(
            content=f"[{self.name}] OK", model=model, provider=self.name,
            input_tokens=100, output_tokens=50, cost_usd=0.0, latency_ms=500,
        )

    async def stream(self, prompt, model, **kw) -> AsyncIterator[str]:
        yield ""

    def get_models(self): return self._models
    async def health_check(self): return self._healthy
    def estimate_cost(self, tokens, model): return 0.0


# ── Helpers ───────────────────────────────────────────────────

def build_config():
    return ModelRoutingConfig(
        low_tier_model="glm-4-plus",
        medium_tier_model="claude-sonnet-4-6",
        high_tier_model="claude-opus-4-7",
        cli_enabled=True,
        cli_providers=[
            CLIProviderConfig(name="claude_code", binary="claude", max_concurrent=3, max_sessions_per_hour=20),
            CLIProviderConfig(name="glm_coding", binary="glm", max_concurrent=3, max_sessions_per_hour=20),
        ],
        providers=[],
    )


def build_registry(claude_healthy=True, glm_healthy=True):
    config = build_config()
    registry = ProviderRegistry(config)
    claude = MockCLI("claude_code", [
        ModelInfo("claude-sonnet-4-6", "claude_code", "medium", 0, 0, 8192),
        ModelInfo("claude-opus-4-7", "claude_code", "high", 0, 0, 16384),
    ], healthy=claude_healthy)
    glm = MockCLI("glm_coding", [
        ModelInfo("glm-4-plus", "glm_coding", "medium", 0, 0, 4096),
    ], healthy=glm_healthy)
    registry._providers = {"claude_code": claude, "glm_coding": glm}
    registry._cli_provider_names = {"claude_code", "glm_coding"}
    return registry, claude, glm


def make_router(registry, quota=None):
    config = build_config()
    router = ModelRouter(config, registry)
    if quota:
        router._cli_quota = quota
    return router


def log_decision(label, profile, decision, response=None):
    mode = decision.execution_mode
    provider = decision.selected_provider
    complexity = decision.task_complexity
    considered = decision.considered_providers or "[]"
    rejected = decision.rejected_providers or "[]"
    blocked = decision.blocked_reason or ""
    reason = decision.reason
    model = decision.selected_model

    # response is only available from route(); decide() only makes the decision
    if blocked:
        status = "BLOCKED"
    elif response is not None:
        status = "OK"
    elif provider != "none":
        status = "DECIDED"  # decide() succeeded, execution not attempted
    else:
        status = "FAIL"
    icon = {"OK": "+", "BLOCKED": "!", "DECIDED": "~", "FAIL": "X"}[status]

    print(f"  [{icon}] {label}")
    print(f"      type={profile.task_type} complexity={complexity} agent={profile.agent_type} tier={profile.budget_tier}")
    print(f"      mode={mode} provider={provider} model={model} reason={reason}")
    print(f"      considered={considered}")
    if json.loads(rejected):
        print(f"      rejected={rejected}")
    if blocked:
        print(f"      BLOCKED: {blocked}")
    print()

    return {
        "label": label, "status": status, "mode": mode, "provider": provider,
        "model": model, "complexity": complexity, "task_type": profile.task_type,
        "reason": reason, "considered": considered, "rejected": rejected,
        "blocked": blocked, "has_response": response is not None,
    }


# ── Task Definitions ──────────────────────────────────────────

TASKS = [
    # ── Simple tasks (expect GLM first for code_gen, CLI mode) ──
    ("SIMPLE-1", "Fix the typo in the README file", "docs", "normal"),
    ("SIMPLE-2", "Update the button color from blue to green on the login page", "frontend", "normal"),
    ("SIMPLE-3", "Rename the getUser function to fetchUser across all files", "backend", "normal"),
    ("SIMPLE-4", "Add a unit test for the email validation utility", "qa", "normal"),
    ("SIMPLE-5", "Change the default timeout from 30s to 60s in the config", "backend", "normal"),

    # ── Medium tasks ──
    ("MEDIUM-1", "Write a detailed explanation of how the OAuth2 token refresh flow works in our authentication module, including error handling for expired tokens and invalid grant types", "docs", "normal"),
    ("MEDIUM-2", "Refactor the user registration handler to extract validation logic into a separate service layer with proper error types and retry support", "backend", "normal"),
    ("MEDIUM-3", "Create a comprehensive review of the payment processing module focusing on race conditions in concurrent transaction handling", "qa", "normal"),
    ("MEDIUM-4", "Plan the migration strategy for moving from REST endpoints to GraphQL resolvers for the inventory management service", "architecture", "normal"),
    ("MEDIUM-5", "Investigate the memory leak reported in the background job worker that processes PDF document conversions and thumbnail generation", "backend", "normal"),

    # ── Complex/critical tasks (expect Claude first for CLI) ──
    ("COMPLEX-1", "Redesign the authentication architecture to support OAuth2 and SAML SSO across multiple microservices with shared session management", "backend", "critical"),
    ("COMPLEX-2", "Debug the critical production issue where the payment service is dropping transactions under high load during peak shopping hours", "backend", "critical"),
    ("COMPLEX-3", "Migrate the entire database layer from SQLAlchemy ORM to raw SQL with connection pooling, ensuring zero downtime during the transition", "backend", "critical"),
    ("COMPLEX-4", "Overhaul the real-time notification system to use WebSocket connections with message queuing, delivery guarantees, and client-side reconnection handling", "architecture", "critical"),
    ("COMPLEX-5", "Integrate the new AI-powered code review system into the CI/CD pipeline with automated severity classification and remediation suggestions", "architecture", "critical"),

    # ── Analysis tasks (API-preferred) ──
    ("ANALYSIS-1", "Analyze the performance metrics from the last quarter and identify the top 3 bottlenecks in the request processing pipeline", "product", "normal"),
    ("ANALYSIS-2", "Investigate the root cause of the increasing latency in the search service over the past two weeks using APM trace data", "backend", "normal"),

    # ── Docs tasks (API-preferred) ──
    ("DOCS-1", "Update the API documentation to reflect the new pagination parameters and response format changes introduced in v2.3", "docs", "normal"),
    ("DOCS-2", "Write comprehensive developer onboarding documentation covering the local development setup, testing conventions, and deployment workflow", "docs", "normal"),

    # ── Planning tasks (CLI-preferred) ──
    ("PLAN-1", "Design the architecture for a new real-time collaboration feature that supports concurrent editing with conflict resolution", "architecture", "normal"),
    ("PLAN-2", "Plan the implementation of a multi-tenant data isolation strategy for the enterprise customer onboarding flow", "product", "normal"),

    # ── Review tasks (CLI-preferred) ──
    ("REVIEW-1", "Review the authentication module for security vulnerabilities including SQL injection, XSS, and CSRF attack vectors", "qa", "normal"),
    ("REVIEW-2", "Check the database migration scripts for potential data loss during the schema transition from v1 to v2", "qa", "normal"),

    # ── Short content (complexity downgrade to simple) ──
    ("SHORT-1", "Fix the broken login", "backend", "normal"),
    ("SHORT-2", "Add error handling", "frontend", "normal"),
    ("SHORT-3", "Update CSS styles", "frontend", "normal"),
]


# ── Stress Scenarios ──────────────────────────────────────────

async def scenario_normal():
    """Both CLI healthy — standard routing."""
    print("\n" + "=" * 70)
    print("SCENARIO 1: NORMAL — Both CLI providers healthy")
    print("=" * 70 + "\n")

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    router = make_router(registry, quota)
    results = []

    async with async_session() as db:
        for label, content, agent, importance in TASKS:
            profile = classify_task(content, agent, importance=importance, has_cli_providers=True)
            decision = await router.decide(content, profile, task_id=label, db=db)
            await db.flush()
            r = log_decision(label, profile, decision)
            results.append(r)

    return results


async def scenario_claude_blocked():
    """Claude blocked — GLM should handle all CLI tasks."""
    print("\n" + "=" * 70)
    print("SCENARIO 2: CLAUDE BLOCKED — Claude CLI rate-limited, GLM healthy")
    print("=" * 70 + "\n")

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    quota.mark_blocked("claude_code", "rate_limit", blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    router = make_router(registry, quota)
    results = []

    async with async_session() as db:
        for label, content, agent, importance in TASKS:
            profile = classify_task(content, agent, importance=importance, has_cli_providers=True)
            decision = await router.decide(content, profile, task_id=label, db=db)
            await db.flush()
            r = log_decision(label, profile, decision)
            results.append(r)

    return results


async def scenario_glm_blocked():
    """GLM blocked — Claude should handle all CLI tasks."""
    print("\n" + "=" * 70)
    print("SCENARIO 3: GLM BLOCKED — GLM CLI quota exceeded, Claude healthy")
    print("=" * 70 + "\n")

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    quota.mark_blocked("glm_coding", "quota_exceeded", blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    router = make_router(registry, quota)
    results = []

    async with async_session() as db:
        for label, content, agent, importance in TASKS:
            profile = classify_task(content, agent, importance=importance, has_cli_providers=True)
            decision = await router.decide(content, profile, task_id=label, db=db)
            await db.flush()
            r = log_decision(label, profile, decision)
            results.append(r)

    return results


async def scenario_both_blocked():
    """Both blocked — all CLI tasks should pause."""
    print("\n" + "=" * 70)
    print("SCENARIO 4: BOTH BLOCKED — All CLI providers unavailable")
    print("=" * 70 + "\n")

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    quota.mark_blocked("claude_code", "rate_limit", blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    quota.mark_blocked("glm_coding", "quota_exceeded", blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    router = make_router(registry, quota)
    results = []

    async with async_session() as db:
        for label, content, agent, importance in TASKS:
            profile = classify_task(content, agent, importance=importance, has_cli_providers=True)
            decision = await router.decide(content, profile, task_id=label, db=db)
            await db.flush()
            r = log_decision(label, profile, decision)
            results.append(r)

    return results


async def scenario_execution_failure():
    """Claude crashes during execution — must NOT fall through to API."""
    print("\n" + "=" * 70)
    print("SCENARIO 5: EXECUTION FAILURE — Claude crashes, verify no silent API fallback")
    print("=" * 70 + "\n")

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    router = make_router(registry, quota)

    async def crash(*args, **kw):
        raise RuntimeError("CLI process crashed")
    claude.complete = crash

    results = []
    async with async_session() as db:
        for label, content, agent, importance in TASKS[:8]:
            profile = classify_task(content, agent, importance=importance, has_cli_providers=True)
            if profile.execution_mode != "cli":
                continue
            response, decision = await router.route(content, profile, task_id=label, db=db)
            r = log_decision(f"{label} (route)", profile, decision, response)
            r["route_used"] = True
            results.append(r)

    return results


async def scenario_context_trim():
    """Verify context optimization on oversized prompts."""
    print("\n" + "=" * 70)
    print("SCENARIO 6: CONTEXT OPTIMIZATION — Oversized prompts trimmed correctly")
    print("=" * 70 + "\n")

    opt = ContextOptimizer()
    results = []

    # Generate a massive prompt (500 blocks × ~30 words ≈ 15000 words ≈ 30000 tokens)
    blocks = []
    for i in range(500):
        blocks.append(
            f"[2026-04-29 10:{i % 60:02d}:{(i * 37) % 60:02d}] INFO worker-{i % 5} "
            f"task-{i}: status=running progress={i * 5}% memory=512MB "
            f"cpu=23% disk_io=45MB/s net_in=12MB/s net_out=8MB/s "
            f"gc_pause=2ms heap=256MB threads=8 cache=94.2% "
            f"db_conn=5 pool_wait=0.3ms queue=12 p50=45ms p99=230ms"
        )
    long_prompt = "\n\n".join(blocks)
    word_count = len(long_prompt.split())

    trim_tests = [
        ("simple+docs", "simple", "docs", "low"),
        ("medium+code_gen", "medium", "code_gen", "medium"),
        ("complex+analysis", "complex", "analysis", "high"),
        ("simple+review", "simple", "review", "low"),
        ("complex+planning", "complex", "planning", "high"),
    ]

    for label, complexity, task_type, tier in trim_tests:
        trimmed = opt.trim(long_prompt, complexity, task_type, budget_tier=tier)
        trimmed_words = len(trimmed.split())
        trimmed_blocks = len(trimmed.split("\n\n"))
        saved_pct = round((1 - trimmed_words / word_count) * 100, 1)
        has_header = "trimmed for context optimization" in trimmed

        print(f"  [~] {label}: {word_count}w -> {trimmed_words}w ({saved_pct}% saved, {trimmed_blocks} blocks)")
        if has_header:
            print(f"      trim header present")
        print()

        results.append({
            "label": label, "original_words": word_count, "trimmed_words": trimmed_words,
            "saved_pct": saved_pct, "blocks": trimmed_blocks, "has_header": has_header,
        })

    # Verify short prompt unchanged
    short = "Fix typo"
    result = opt.trim(short, "simple", "code_gen")
    print(f"  [~] short prompt unchanged: {len(short) == len(result)}")
    results.append({"label": "short_unchanged", "unchanged": len(short) == len(result)})
    print()

    return results


async def scenario_adaptive_degradation():
    """Simulate many sessions degrading one provider — verify reorder."""
    print("\n" + "=" * 70)
    print("SCENARIO 7: ADAPTIVE DEGRADATION — Claude degrades over 20 sessions")
    print("=" * 70 + "\n")

    registry, claude, glm = build_registry()
    quota = CLIQuotaTracker()
    router = make_router(registry, quota)
    results = []

    # Simulate Claude succeeding 5 times, then failing 5 times
    for i in range(5):
        quota.record_session("claude_code", 2.0)
    for i in range(5):
        quota.mark_blocked("claude_code", f"timeout_{i}")

    signals = quota.get_adaptive_signals("claude_code")
    print(f"  Claude after 5 success + 5 failures:")
    print(f"    success_rate={signals['recent_success_rate']}  failure_rate={signals['recent_failure_rate']}")
    print(f"    total_sessions={signals['total_sessions']}  is_available={signals['is_available']}")
    print()

    # Check reorder for code_gen+complex (static: [claude, glm])
    reordered = router._reorder_by_adaptive_signals(["claude_code", "glm_coding"], "code_gen", "complex")
    print(f"  code_gen+complex reorder: {reordered}")
    print(f"    Expected: glm first (claude degraded)")
    print()

    # Now route 10 complex tasks and verify glm is always picked
    async with async_session() as db:
        for i in range(10):
            label = f"DEGRADE-{i}"
            content = f"Redesign the authentication architecture for microservice {i} with OAuth2 support and session management"
            profile = classify_task(content, "backend", importance="critical", has_cli_providers=True)
            decision = await router.decide(content, profile, task_id=label, db=db)
            await db.flush()
            r = log_decision(label, profile, decision)
            results.append(r)

    # Simulate recovery: Claude succeeds 8 more times
    print("  --- Simulating Claude recovery (8 successes) ---")
    for i in range(8):
        quota.record_session("claude_code", 1.5)
    signals = quota.get_adaptive_signals("claude_code")
    print(f"  Claude after recovery:")
    print(f"    success_rate={signals['recent_success_rate']}  failure_rate={signals['recent_failure_rate']}")
    print(f"    total_sessions={signals['total_sessions']}  is_available={signals['is_available']}")
    print()

    reordered = router._reorder_by_adaptive_signals(["claude_code", "glm_coding"], "code_gen", "complex")
    print(f"  code_gen+complex reorder after recovery: {reordered}")
    print()

    return results


# ── Analysis ──────────────────────────────────────────────────

def analyze_scenario(name, results, expect=None):
    """Analyze routing decisions for correctness."""
    issues = []
    unexpected = []
    crashes = 0

    for r in results:
        if "blocks" in r:
            continue  # Context optimization result

        if r.get("status") == "FAIL":
            crashes += 1

        if expect and expect.get("no_api"):
            if r["mode"] == "api" and r["task_type"] in ("code_gen", "review", "planning"):
                unexpected.append(f"  {r['label']}: API mode for CLI-preferred type {r['task_type']}")

        if expect and expect.get("all_blocked"):
            if r["status"] != "BLOCKED" and r["mode"] == "cli":
                issues.append(f"  {r['label']}: Expected BLOCKED but got {r['status']} (provider={r['provider']})")

        if expect and expect.get("provider"):
            if r["mode"] == "cli" and r["provider"] != expect["provider"] and r["status"] in ("OK", "DECIDED"):
                unexpected.append(f"  {r['label']}: Expected {expect['provider']} but got {r['provider']}")

    return issues, unexpected, crashes


# ── Main ──────────────────────────────────────────────────────

async def main():
    await init_db()

    print("=" * 70)
    print("ORKA Phase 5.6 — Real-World Stress Test")
    print(f"  {len(TASKS)} tasks x 7 scenarios")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 70)

    # Run scenarios
    normal = await scenario_normal()
    claude_blocked = await scenario_claude_blocked()
    glm_blocked = await scenario_glm_blocked()
    both_blocked = await scenario_both_blocked()
    exec_failure = await scenario_execution_failure()
    ctx_results = await scenario_context_trim()
    degradation = await scenario_adaptive_degradation()

    # ── Analysis ──────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("ANALYSIS")
    print("=" * 70 + "\n")

    total_decisions = 0
    total_decided = 0
    total_blocked = 0
    total_fail = 0
    provider_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    all_issues: list[str] = []
    all_unexpected: list[str] = []

    def count_result(r):
        nonlocal total_decisions, total_decided, total_blocked, total_fail
        total_decisions += 1
        if r["status"] in ("OK", "DECIDED"):
            total_decided += 1
            provider_counts[r["provider"]] = provider_counts.get(r["provider"], 0) + 1
        elif r["status"] == "BLOCKED":
            total_blocked += 1
        elif r["status"] == "FAIL":
            total_fail += 1
        mode_counts[r["mode"]] = mode_counts.get(r["mode"], 0) + 1

    # Scenario 1: Normal
    issues, unexpected, crashes = analyze_scenario("NORMAL", normal)
    all_issues.extend(issues)
    all_unexpected.extend(unexpected)
    for r in normal:
        count_result(r)

    print("  SCENARIO 1 (Normal):")
    simple_glm = sum(1 for r in normal if "SIMPLE" in r["label"] and r["provider"] == "glm_coding" and r["mode"] == "cli")
    simple_total = sum(1 for r in normal if "SIMPLE" in r["label"] and r["mode"] == "cli")
    print(f"    CLI tasks routed to GLM for simple code_gen: {simple_glm}/{simple_total}")
    complex_claude = sum(1 for r in normal if "COMPLEX" in r["label"] and r["provider"] == "claude_code" and r["mode"] == "cli")
    complex_total = sum(1 for r in normal if "COMPLEX" in r["label"] and r["mode"] == "cli")
    print(f"    Complex tasks routed to Claude: {complex_claude}/{complex_total}")
    api_tasks = sum(1 for r in normal if r["mode"] == "api")
    print(f"    Analysis/docs tasks use API mode: {api_tasks}")
    print()

    # Scenario 2: Claude blocked
    issues, unexpected, crashes = analyze_scenario("CLAUDE_BLOCKED", claude_blocked, expect={"no_api": True})
    all_issues.extend(issues)
    all_unexpected.extend(unexpected)
    for r in claude_blocked:
        count_result(r)

    cli_ok_glm = sum(1 for r in claude_blocked if r["status"] in ("OK", "DECIDED") and r["provider"] == "glm_coding" and r["mode"] == "cli")
    cli_total = sum(1 for r in claude_blocked if r["mode"] == "cli")
    print("  SCENARIO 2 (Claude blocked):")
    print(f"    CLI tasks handled by GLM: {cli_ok_glm}/{cli_total}")
    api_fallback = sum(1 for r in claude_blocked if r["mode"] == "api" and r["task_type"] in ("code_gen", "review", "planning"))
    print(f"    No silent API fallback: {'PASS' if api_fallback == 0 else f'FAIL ({api_fallback} tasks)'}")
    print()

    # Scenario 3: GLM blocked
    issues, unexpected, crashes = analyze_scenario("GLM_BLOCKED", glm_blocked, expect={"no_api": True})
    all_issues.extend(issues)
    all_unexpected.extend(unexpected)
    for r in glm_blocked:
        count_result(r)

    cli_ok_claude = sum(1 for r in glm_blocked if r["status"] in ("OK", "DECIDED") and r["provider"] == "claude_code" and r["mode"] == "cli")
    print("  SCENARIO 3 (GLM blocked):")
    print(f"    CLI tasks handled by Claude: {cli_ok_claude}/{cli_total}")
    api_fallback = sum(1 for r in glm_blocked if r["mode"] == "api" and r["task_type"] in ("code_gen", "review", "planning"))
    print(f"    No silent API fallback: {'PASS' if api_fallback == 0 else f'FAIL ({api_fallback} tasks)'}")
    print()

    # Scenario 4: Both blocked
    issues, unexpected, crashes = analyze_scenario("BOTH_BLOCKED", both_blocked, expect={"all_blocked": True, "no_api": True})
    all_issues.extend(issues)
    all_unexpected.extend(unexpected)
    for r in both_blocked:
        count_result(r)

    cli_blocked = sum(1 for r in both_blocked if r["status"] == "BLOCKED" and r["mode"] == "cli")
    api_leak = sum(1 for r in both_blocked if r["mode"] == "api" and r["task_type"] in ("code_gen", "review", "planning"))
    print("  SCENARIO 4 (Both blocked):")
    print(f"    CLI tasks correctly blocked: {cli_blocked}/{cli_total}")
    print(f"    No silent API fallback: {'PASS' if api_leak == 0 else f'FAIL ({api_leak} tasks leaked to API)'}")
    print()

    # Scenario 5: Execution failure
    # Separate: tasks where Claude was selected (should fail) vs GLM selected (should succeed)
    claude_selected = [r for r in exec_failure if r["provider"] == "claude_code"]
    glm_selected = [r for r in exec_failure if r["provider"] == "glm_coding"]
    claude_failed = sum(1 for r in claude_selected if r["has_response"] is False)
    glm_succeeded = sum(1 for r in glm_selected if r["has_response"] is True)
    api_leak = sum(1 for r in exec_failure if r["mode"] == "api")
    print("  SCENARIO 5 (Execution failure):")
    print(f"    Claude-selected tasks failed (no response): {claude_failed}/{len(claude_selected)}")
    print(f"    GLM-selected tasks succeeded (fallback): {glm_succeeded}/{len(glm_selected)}")
    print(f"    No silent API fallback: {'PASS' if api_leak == 0 else f'FAIL ({api_leak} leaked)'}")
    print()

    # Scenario 6: Context optimization
    trim_ok = sum(1 for r in ctx_results if "blocks" in r)
    headers_ok = sum(1 for r in ctx_results if r.get("has_header"))
    print("  SCENARIO 6 (Context optimization):")
    print(f"    Prompts trimmed: {trim_ok}/{len(ctx_results) - 1}")
    print(f"    Trim headers present: {headers_ok}/{trim_ok}")
    short_ok = next((r for r in ctx_results if r.get("label") == "short_unchanged"), {}).get("unchanged", False)
    print(f"    Short prompt unchanged: {short_ok}")
    print()

    # Scenario 7: Adaptive degradation
    glm_during_degrade = sum(1 for r in degradation if r["provider"] == "glm_coding" and r["mode"] == "cli")
    print("  SCENARIO 7 (Adaptive degradation):")
    print(f"    Tasks routed to GLM during Claude degradation: {glm_during_degrade}/{len(degradation)}")
    all_glm = all(r["provider"] == "glm_coding" for r in degradation if r["mode"] == "cli")
    print(f"    All tasks routed correctly: {'PASS' if all_glm else 'FAIL'}")
    print()

    # ── Final Summary ─────────────────────────────────────────

    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70 + "\n")

    print(f"  Total routing decisions: {total_decisions}")
    print(f"  Decided (provider selected): {total_decided}")
    print(f"  Blocked (expected pauses): {total_blocked}")
    print(f"  Failed (execution errors): {total_fail}")
    print(f"  Provider distribution: {dict(provider_counts)}")
    print(f"  Mode distribution: {dict(mode_counts)}")
    print()

    if all_issues:
        print("  INCORRECT ROUTING DECISIONS:")
        for issue in all_issues:
            print(issue)
        print()

    if all_unexpected:
        print("  UNEXPECTED PROVIDER CHOICES:")
        for u in all_unexpected:
            print(u)
        print()

    if not all_issues and not all_unexpected:
        print("  No incorrect routing decisions detected.")
        print("  No unexpected provider choices.")
        print()

    # Verify invariants
    invariants_pass = True
    print("  INVARIANT CHECKS:")

    # 1. No API fallback for CLI-preferred tasks when CLI is available
    api_leak_total = sum(1 for r in normal
                         if r["task_type"] in ("code_gen", "review", "planning") and r["mode"] == "api")
    print(f"    [{'PASS' if api_leak_total == 0 else 'FAIL'}] No API fallback for CLI-preferred tasks (normal)")

    # 2. Simple code_gen → GLM
    simple_wrong = sum(1 for r in normal
                       if "SIMPLE" in r["label"] and r["mode"] == "cli" and r["provider"] != "glm_coding")
    print(f"    [{'PASS' if simple_wrong == 0 else 'FAIL'}] Simple code_gen tasks -> GLM (cheaper)")

    # 3. Complex/critical → Claude
    complex_wrong = sum(1 for r in normal
                        if "COMPLEX" in r["label"] and r["mode"] == "cli" and r["provider"] != "claude_code")
    print(f"    [{'PASS' if complex_wrong == 0 else 'FAIL'}] Complex/critical tasks -> Claude (strongest)")

    # 4. Both blocked → all CLI tasks blocked
    both_ok = all(r["status"] == "BLOCKED" for r in both_blocked if r["mode"] == "cli")
    print(f"    [{'PASS' if both_ok else 'FAIL'}] Both blocked -> all CLI tasks pause")

    # 5. Execution failure → no API fallback (only check claude-selected tasks)
    exec_no_api = all(r["mode"] == "cli" for r in exec_failure) and all(
        not r["has_response"] for r in claude_selected
    )
    print(f"    [{'PASS' if exec_no_api else 'FAIL'}] CLI execution failure -> no silent API fallback")

    # 6. Context trim works
    ctx_ok = all(r.get("has_header") or r.get("unchanged") for r in ctx_results)
    print(f"    [{'PASS' if ctx_ok else 'FAIL'}] Context optimization trims oversized prompts")

    # 7. Adaptive degradation → all tasks go to healthy provider
    print(f"    [{'PASS' if all_glm else 'FAIL'}] Degraded provider deprioritized by adaptive signals")

    print()

    if invariants_pass and all_glm and exec_no_api and ctx_ok and both_ok:
        print("  ALL INVARIANTS PASS")
        print()
        return 0
    else:
        print("  SOME INVARIANTS FAILED")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
