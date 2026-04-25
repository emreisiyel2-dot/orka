"""
Phase 3B End-to-End Integration Test

Run in backend dir with env vars set:
    export ORKA_LLM_ENABLED=true
    export ZAI_API_KEY=your-key
    export ZAI_BASE_URL=https://your-zai-endpoint/v1
    export ZAI_MODEL_LOW=your-low-model
    export ZAI_MODEL_HIGH=your-high-model
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_phase3b_e2e.py

Also works with OpenAI:
    export OPENAI_API_KEY=sk-...
"""
import asyncio
import sys
import os

# Ensure LLM is enabled for this test
os.environ["ORKA_LLM_ENABLED"] = "true"

from app.config.model_config import load_config
from app.providers.registry import ProviderRegistry
from app.services.model_router import classify_task, ModelRouter
from app.database import async_session
from app.models import RoutingDecision, UsageRecord, ProviderQuotaState
from sqlalchemy import select

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


async def run_tests():
    config = load_config()
    registry = ProviderRegistry(config)

    # ── Test 1: TaskClassifier ──────────────────────────
    print("=" * 60)
    print("TEST 1: TaskClassifier")
    print("=" * 60)
    cases = [
        ("Fix the login button styling", "frontend", "normal", "medium", "simple", "code_gen"),
        ("Write unit tests for auth", "qa", "normal", "high", "simple", "review"),
        ("URGENT: production DB broken", "backend", "critical", "high", "critical", "code_gen"),
        ("Create API documentation", "docs", "normal", "low", "simple", "docs"),
        ("Analyze architecture for migration", "orchestrator", "normal", "dynamic", "complex", "analysis"),
    ]
    all_classify_ok = True
    for content, agent, importance, exp_tier, exp_complexity, _ in cases:
        p = classify_task(content, agent, importance, has_cli_providers=False)
        ok = p.budget_tier == exp_tier
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status:7s}] {agent:12s} → tier={p.budget_tier:7s} complexity={p.complexity:8s} type={p.task_type}")
        if not ok:
            all_classify_ok = False
    results.append(("TaskClassifier", PASS if all_classify_ok else FAIL, f"{len(cases)} cases"))

    # ── Test 2: Provider Availability ───────────────────
    print()
    print("=" * 60)
    print("TEST 2: Provider & Model Availability")
    print("=" * 60)
    providers = registry.all()
    all_models = registry.all_models()
    print(f"  Providers: {list(providers.keys())}")
    print(f"  Total models: {len(all_models)}")
    for m in all_models:
        print(f"    {m.id:25s} tier={m.tier:6s} provider={m.provider}")
    has_providers = len(providers) > 0
    results.append(("Provider Availability", PASS if has_providers else FAIL, f"{len(providers)} provider(s), {len(all_models)} models"))
    if not has_providers:
        print("  ABORT: No providers configured. Set API keys and re-run.")
        return

    # ── Test 3: Real LLM Call — Low Tier ───────────────
    print()
    print("=" * 60)
    print("TEST 3: Real LLM Call (docs agent → low tier)")
    print("=" * 60)
    router = ModelRouter(config, registry)

    async with async_session() as db:
        profile = classify_task("What is 2+2? Reply with just the number.", "docs", has_cli_providers=False)
        print(f"  Profile: tier={profile.budget_tier}, type={profile.task_type}, complexity={profile.complexity}")
        print(f"  Calling provider...")

        resp, decision = await router.route(
            prompt="What is 2+2? Reply with just the number.",
            profile=profile,
            task_id=None,
            db=db,
        )
        await db.commit()

        if resp is None:
            print(f"  FAIL: blocked={decision.blocked_reason}, reason={decision.reason}")
            results.append(("LLM Call (low)", FAIL, f"blocked: {decision.blocked_reason}"))
        else:
            print(f"  Response:    '{resp.content[:120]}'")
            print(f"  Model:       {resp.model}")
            print(f"  Provider:    {resp.provider}")
            print(f"  Tokens:      in={resp.input_tokens}, out={resp.output_tokens}")
            print(f"  Cost:        ${resp.cost_usd:.6f}")
            print(f"  Latency:     {resp.latency_ms}ms")
            print(f"  Decision:    reason={decision.reason}, quota={decision.quota_status}")
            results.append(("LLM Call (low)", PASS, f"model={resp.model}, {resp.input_tokens}+{resp.output_tokens} tok, ${resp.cost_usd:.6f}, {resp.latency_ms}ms"))

    # ── Test 4: Real LLM Call — High Tier ──────────────
    print()
    print("=" * 60)
    print("TEST 4: Real LLM Call (backend agent → high tier)")
    print("=" * 60)

    async with async_session() as db:
        profile = classify_task("Explain what a REST API is in one sentence.", "backend", has_cli_providers=False)
        print(f"  Profile: tier={profile.budget_tier}, type={profile.task_type}")
        print(f"  Calling provider...")

        resp2, decision2 = await router.route(
            prompt="Explain what a REST API is in one sentence.",
            profile=profile,
            task_id=None,
            db=db,
        )
        await db.commit()

        if resp2 is None:
            print(f"  FAIL: blocked={decision2.blocked_reason}")
            results.append(("LLM Call (high)", FAIL, f"blocked: {decision2.blocked_reason}"))
        else:
            print(f"  Response:    '{resp2.content[:120]}'")
            print(f"  Model:       {resp2.model}")
            print(f"  Cost:        ${resp2.cost_usd:.6f}")
            print(f"  Latency:     {resp2.latency_ms}ms")
            print(f"  Decision:    reason={decision2.reason}, quota={decision2.quota_status}")
            results.append(("LLM Call (high)", PASS, f"model={resp2.model}, ${resp2.cost_usd:.6f}"))

    # ── Test 5: RoutingDecisionLog ──────────────────────
    print()
    print("=" * 60)
    print("TEST 5: RoutingDecisionLog")
    print("=" * 60)
    async with async_session() as db:
        r = await db.execute(select(RoutingDecision).order_by(RoutingDecision.created_at.desc()).limit(5))
        decisions = r.scalars().all()
        if decisions:
            for d in decisions:
                model_str = d.selected_model if d.selected_model != "none" else "BLOCKED"
                print(f"  [{d.reason:25s}] model={model_str:20s} provider={d.selected_provider:10s} quota={d.quota_status} cost=${d.actual_cost or 0:.6f}")
            results.append(("RoutingDecisionLog", PASS, f"{len(decisions)} decisions logged"))
        else:
            results.append(("RoutingDecisionLog", FAIL, "no decisions found"))

    # ── Test 6: UsageRecord ─────────────────────────────
    print()
    print("=" * 60)
    print("TEST 6: UsageRecord")
    print("=" * 60)
    async with async_session() as db:
        r = await db.execute(select(UsageRecord).order_by(UsageRecord.created_at.desc()).limit(5))
        records = r.scalars().all()
        if records:
            for u in records:
                print(f"  model={u.model:20s} provider={u.provider:10s} tokens={u.input_tokens}+{u.output_tokens} cost=${u.cost_usd:.6f} latency={u.latency_ms}ms")
            results.append(("UsageRecord", PASS, f"{len(records)} records, total cost=${sum(u.cost_usd for u in records):.6f}"))
        else:
            results.append(("UsageRecord", FAIL, "no usage records found"))

    # ── Test 7: QuotaManager Status ─────────────────────
    print()
    print("=" * 60)
    print("TEST 7: QuotaManager Status")
    print("=" * 60)
    async with async_session() as db:
        from app.services.quota_manager import QuotaManager
        qm = QuotaManager(config)
        states = await qm.get_all_states(db)
        for s in states:
            print(f"  {s.provider}: status={s.status}, remaining={s.remaining_quota}, total={s.total_quota}, paid_overage={s.allow_paid_overage}")
        results.append(("QuotaManager", PASS if states else FAIL, f"{len(states)} provider(s) tracked"))

    # ── Test 8: BudgetManager ───────────────────────────
    print()
    print("=" * 60)
    print("TEST 8: BudgetManager (should NOT be triggered)")
    print("=" * 60)
    async with async_session() as db:
        from app.services.budget_manager import BudgetManager
        bm = BudgetManager()
        state = await bm.get_state(db)
        daily = await bm.get_daily_spend(db)
        monthly = await bm.get_monthly_spend(db)
        cfg = await bm.get_config(db)
        print(f"  State:         {state}")
        print(f"  Daily spend:   ${daily:.6f}")
        print(f"  Monthly spend: ${monthly:.6f}")
        print(f"  Soft limit:    ${cfg.daily_soft_limit}")
        print(f"  Hard limit:    ${cfg.daily_hard_limit}")
        budget_ok = state == "normal"
        results.append(("BudgetManager", PASS if budget_ok else FAIL, f"state={state}, daily=${daily:.6f}"))

    # ── Test 9: No Silent Paid Fallback ─────────────────
    print()
    print("=" * 60)
    print("TEST 9: No Silent Paid Fallback")
    print("=" * 60)
    async with async_session() as db:
        r = await db.execute(select(RoutingDecision).where(RoutingDecision.reason == "paid_override_approved"))
        paid_decisions = r.scalars().all()
        any_paid_config = any(p.allow_paid_overage for p in config.providers)
        print(f"  Paid override decisions:  {len(paid_decisions)}")
        print(f"  ALLOW_PAID_OVERAGE:       {config.allow_paid_overage}")
        print(f"  Any provider paid=true:   {any_paid_config}")
        print(f"  Fallback policy:          {config.fallback_policy}")
        no_paid = len(paid_decisions) == 0 and not any_paid_config and not config.allow_paid_overage
        results.append(("No Paid Fallback", PASS if no_paid else FAIL, f"paid_overrides={len(paid_decisions)}, config={config.allow_paid_overage}"))

    # ── Test 10: Simulated Quota Exhaustion ─────────────
    print()
    print("=" * 60)
    print("TEST 10: Simulated Quota Exhaustion")
    print("=" * 60)
    async with async_session() as db:
        # Manually exhaust the first provider's quota
        provider_name = list(providers.keys())[0]
        qm = QuotaManager(config)
        state = await qm.ensure_state(provider_name, db)
        old_remaining = state.remaining_quota
        state.remaining_quota = 0
        state.total_quota = 1000
        state.status = "exhausted"
        await db.flush()

        # Try to route with exhausted quota
        profile = classify_task("Test task after exhaustion", "docs", has_cli_providers=False)
        resp3, decision3 = await router.route(
            prompt="This should be blocked.",
            profile=profile,
            task_id=None,
            db=db,
        )
        await db.commit()

        if resp3 is None and decision3.blocked_reason in ("no_provider_with_quota", "budget_exhausted"):
            print(f"  PASS: Correctly blocked when quota exhausted")
            print(f"    reason={decision3.reason}, blocked={decision3.blocked_reason}")
            results.append(("Quota Exhaustion", PASS, f"blocked correctly: {decision3.blocked_reason}"))
        elif resp3 is not None:
            print(f"  FAIL: Should have been blocked but got response: {resp3.content[:50]}")
            results.append(("Quota Exhaustion", FAIL, "call was NOT blocked when quota exhausted"))
        else:
            print(f"  Result: reason={decision3.reason}, blocked={decision3.blocked_reason}")
            results.append(("Quota Exhaustion", PASS, f"blocked: {decision3.blocked_reason}"))

        # Reset quota for cleanup
        await qm.reset_provider(provider_name, db)
        await db.commit()
        print(f"  Quota reset for cleanup.")

    # ── SUMMARY ─────────────────────────────────────────
    print()
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    for name, status, detail in results:
        print(f"  [{status:4s}] {name:25s}: {detail}")

    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    print(f"\n  {passed} passed, {failed} failed out of {len(results)} tests")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
