"""
Phase 5.6: Smart Routing Test Suite

Validates all Phase 5.6 features:
1. ContextOptimizer — trim short (no-op), trim long, complexity-based windows, custom limits, adaptive tier limits
2. Routing policy lookup — lookup_cli_policy() correctness
3. Model selection by complexity — _select_model_by_complexity with mock ModelInfo
4. CLIQuotaTracker enriched fields — last_success_at, last_error, last_failure_at, counts, last_health_check
5. CLIQuotaTracker.is_available() — unknown, blocked, failure_rate threshold, healthy
6. CLIQuotaTracker.get_adaptive_signals() — rates, totals, defaults
7. CLIQuotaTracker.get_provider_status() — full dict, None for unknown, signals included
8. RoutingDecision new columns — class attribute existence and nullability
9. System stats provider key — import check
10. decide() purity — policy importability, _CLI_ROUTING_POLICY entries, _reorder threshold values

Run from backend dir:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_smart_routing.py
"""

import sys
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.context_optimizer import ContextOptimizer, _TIER_TOKEN_LIMITS, _HISTORY_WINDOW, _DEFAULT_HISTORY_WINDOW
from app.services.model_router import (
    lookup_cli_policy,
    _CLI_ROUTING_POLICY,
    _CLI_DEFAULT_ORDER,
    ModelRouter,
    TaskProfile,
)
from app.services.cli_quota_tracker import CLIQuotaTracker, CLISessionUsage

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {name} {detail}")


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeModelInfo:
    id: str
    tier: str = "medium"


def _make_router():
    """Create a ModelRouter with minimal mocked dependencies."""
    config = MagicMock()
    config.cli_providers = []
    registry = MagicMock()
    return ModelRouter(config, registry)


# ===========================================================================
# 1. ContextOptimizer
# ===========================================================================

def _make_long_block(words_per_block: int = 50) -> str:
    """Create a single paragraph block with approximately words_per_block words."""
    return " ".join([f"word{i}" for i in range(words_per_block)])


def test_context_optimizer():
    print("\n--- 1. ContextOptimizer ---")

    opt = ContextOptimizer()
    # Default max_tokens for medium tier = 8000, so max_words = 4000

    # 1a. trim short prompt — no-op
    short = "Hello world, this is a short prompt."
    result = opt.trim(short, "simple", "code_gen")
    check("trim short prompt returns unchanged", result == short)

    # 1b. trim long prompt
    # 200 blocks * 50 words = 10000 words > 4000 max_words
    long_prompt = "\n\n".join([_make_long_block(50) for _ in range(200)])
    result = opt.trim(long_prompt, "simple", "docs")
    check("trim long prompt actually reduces length",
          len(result.split()) < len(long_prompt.split()))
    check("trimmed prompt contains optimization header",
          "trimmed for context optimization" in result)

    # 1c. complexity-based history windows
    # 200 blocks with 50 words each = 10000 words (exceeds 4000 max_words)
    many_blocks = "\n\n".join([_make_long_block(50) for _ in range(200)])

    # complex analysis should keep 10 blocks
    result_complex = opt.trim(many_blocks, "complex", "analysis")
    kept_blocks = result_complex.replace("[", "").split("\n\n")
    # Should keep last 10 blocks + 1 header line = ~11 parts when split
    check("complex analysis keeps ~10 blocks",
          10 <= len(kept_blocks) <= 12)

    # simple docs should keep 3 blocks
    result_simple = opt.trim(many_blocks, "simple", "docs")
    kept_blocks_simple = result_simple.replace("[", "").split("\n\n")
    check("simple docs keeps ~3 blocks",
          3 <= len(kept_blocks_simple) <= 5)

    # default should keep 5 blocks
    result_default = opt.trim(many_blocks, "medium", "code_gen")
    kept_blocks_default = result_default.replace("[", "").split("\n\n")
    check("default keeps ~5 blocks",
          5 <= len(kept_blocks_default) <= 7)

    # 1d. custom max_context_tokens
    opt_custom = ContextOptimizer(max_context_tokens=100)
    # 100 tokens / 2 tokens_per_word = 50 words max
    # Use \n\n separated blocks so trimming can work
    # Use ("docs", "simple") which has keep_recent=3 in _HISTORY_WINDOW
    tiny_prompt = "\n\n".join([_make_long_block(20) for _ in range(10)])
    # 10 blocks * 20 words = 200 words > 50 max_words
    result_custom = opt_custom.trim(tiny_prompt, "simple", "docs")
    # docs+simple keeps 3 blocks * 20 words = 60 words + ~8 word header = ~68 words
    check("custom max_context_tokens limits output",
          len(result_custom.split()) <= 75)  # allow margin for header

    # 1e. adaptive budget tier limits — low keeps fewer blocks than high
    # low tier: max 4000 tokens = 2000 words; high tier: max 16000 tokens = 8000 words
    # With 200 blocks * 50 words = 10000 words:
    #   low tier (2000 words max) will trim aggressively
    #   high tier (8000 words max) will also trim but keep more
    result_low = opt.trim(many_blocks, "medium", "code_gen", budget_tier="low")
    result_high = opt.trim(many_blocks, "medium", "code_gen", budget_tier="high")

    # low tier should produce shorter output than high tier
    check("adaptive tier: low produces shorter output than high",
          len(result_low.split()) <= len(result_high.split()))

    # Verify _TIER_TOKEN_LIMITS has expected entries
    check("_TIER_TOKEN_LIMITS has 'low' entry", "low" in _TIER_TOKEN_LIMITS)
    check("_TIER_TOKEN_LIMITS has 'high' entry", "high" in _TIER_TOKEN_LIMITS)
    low_high = _TIER_TOKEN_LIMITS["high"][1]
    low_low = _TIER_TOKEN_LIMITS["low"][1]
    check("_TIER_TOKEN_LIMITS high > low", low_high > low_low)


# ===========================================================================
# 2. Routing policy lookup
# ===========================================================================

def test_routing_policy_lookup():
    print("\n--- 2. Routing policy lookup ---")

    # 2a. code_gen + simple -> ["glm_coding", "claude_code"]
    result = lookup_cli_policy("code_gen", "simple")
    check("code_gen+simple -> glm_coding first",
          result == ["glm_coding", "claude_code"])

    # 2b. code_gen + complex -> ["claude_code", "glm_coding"]
    result = lookup_cli_policy("code_gen", "complex")
    check("code_gen+complex -> claude_code first",
          result == ["claude_code", "glm_coding"])

    # 2c. analysis + complex -> ["claude_code"]
    result = lookup_cli_policy("analysis", "complex")
    check("analysis+complex -> claude_code only",
          result == ["claude_code"])

    # 2d. unknown combination -> default order
    result = lookup_cli_policy("unknown_type", "unknown_level")
    check("unknown combo -> default order",
          result == _CLI_DEFAULT_ORDER)


# ===========================================================================
# 3. Model selection by complexity
# ===========================================================================

def test_model_selection_by_complexity():
    print("\n--- 3. Model selection by complexity ---")

    router = _make_router()

    models = [
        FakeModelInfo(id="cheap-model", tier="low"),
        FakeModelInfo(id="mid-model", tier="medium"),
        FakeModelInfo(id="strong-model", tier="high"),
    ]

    # 3a. simple -> cheapest (lowest tier)
    result = router._select_model_by_complexity(models, "simple")
    check("simple selects cheapest model", result == "cheap-model")

    # 3b. complex -> strongest (highest tier)
    result = router._select_model_by_complexity(models, "complex")
    check("complex selects strongest model", result == "strong-model")

    # 3c. medium -> middle tier
    result = router._select_model_by_complexity(models, "medium")
    check("medium selects mid model", result == "mid-model")

    # 3d. empty list -> "unknown"
    result = router._select_model_by_complexity([], "simple")
    check("empty list returns 'unknown'", result == "unknown")


# ===========================================================================
# 4. CLIQuotaTracker enriched fields
# ===========================================================================

def test_cli_quota_tracker_enriched_fields():
    print("\n--- 4. CLIQuotaTracker enriched fields ---")

    tracker = CLIQuotaTracker()

    # 4a. record_session sets last_success_at and increments recent_success_count
    tracker.record_session("prov_a", duration_seconds=5.0)
    usage = tracker.get_usage("prov_a")
    check("record_session sets last_success_at",
          usage.last_success_at is not None)
    check("record_session increments recent_success_count",
          usage.recent_success_count == 1)

    # 4b. mark_blocked sets last_error, last_failure_at, recent_failure_count
    tracker.mark_blocked("prov_b", reason="rate_limit_exceeded")
    usage_b = tracker.get_usage("prov_b")
    check("mark_blocked sets last_error",
          usage_b.last_error == "rate_limit_exceeded")
    check("mark_blocked sets last_failure_at",
          usage_b.last_failure_at is not None)
    check("mark_blocked increments recent_failure_count",
          usage_b.recent_failure_count == 1)

    # 4c. check_available sets last_health_check
    tracker.check_available("prov_a")
    usage_a = tracker.get_usage("prov_a")
    check("check_available sets last_health_check",
          usage_a.last_health_check is not None)

    # 4d. Multiple records increment correctly
    tracker.record_session("prov_c", duration_seconds=2.0)
    tracker.record_session("prov_c", duration_seconds=3.0)
    tracker.record_session("prov_c", duration_seconds=4.0)
    usage_c = tracker.get_usage("prov_c")
    check("multiple records increment recent_success_count to 3",
          usage_c.recent_success_count == 3)
    check("total_duration accumulates correctly",
          usage_c.total_duration_seconds == 9.0)


# ===========================================================================
# 5. CLIQuotaTracker.is_available()
# ===========================================================================

def test_cli_quota_tracker_is_available():
    print("\n--- 5. CLIQuotaTracker.is_available() ---")

    # 5a. Unknown provider returns True
    tracker = CLIQuotaTracker()
    check("unknown provider is available",
          tracker.is_available("nonexistent_provider") is True)

    # 5b. Blocked provider returns False
    tracker.mark_blocked("blocked_prov", reason="test_block",
                         blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    check("blocked provider is not available",
          tracker.is_available("blocked_prov") is False)

    # 5c. Blocked provider with expired block returns True
    tracker.mark_blocked("expired_prov", reason="test",
                         blocked_until=datetime.now(timezone.utc) - timedelta(hours=1))
    check("expired block returns available",
          tracker.is_available("expired_prov") is True)

    # 5d. Failure rate > 50% with >=3 sessions returns False
    tracker2 = CLIQuotaTracker()
    # Record 2 successes
    tracker2.record_session("fail_prov", duration_seconds=1.0)
    tracker2.record_session("fail_prov", duration_seconds=1.0)
    # Record 3 failures (total 5, failure_rate = 3/5 = 60% > 50%)
    tracker2.mark_blocked("fail_prov", reason="fail1",
                          blocked_until=None)
    # mark_blocked only increments recent_failure_count by 1 and sets status=blocked
    # We need to manipulate directly to test the is_available failure_rate logic
    # without the blocked status overriding. Let's create a provider with
    # custom counts.
    tracker3 = CLIQuotaTracker()
    usage = tracker3._get_or_create("high_fail")
    usage.recent_success_count = 2
    usage.recent_failure_count = 3
    usage.status = "available"  # explicitly not blocked
    check("failure_rate > 50% with >=3 sessions is not available",
          tracker3.is_available("high_fail") is False)

    # 5e. Low failure rate returns True
    tracker4 = CLIQuotaTracker()
    usage4 = tracker4._get_or_create("low_fail")
    usage4.recent_success_count = 8
    usage4.recent_failure_count = 1
    usage4.status = "available"
    check("low failure_rate is available",
          tracker4.is_available("low_fail") is True)

    # 5f. Exactly 50% failure rate (not > 50%) returns True
    tracker5 = CLIQuotaTracker()
    usage5 = tracker5._get_or_create("exact_50")
    usage5.recent_success_count = 2
    usage5.recent_failure_count = 2
    usage5.status = "available"
    check("exactly 50% failure rate is available",
          tracker5.is_available("exact_50") is True)


# ===========================================================================
# 6. CLIQuotaTracker.get_adaptive_signals()
# ===========================================================================

def test_cli_quota_tracker_adaptive_signals():
    print("\n--- 6. CLIQuotaTracker.get_adaptive_signals() ---")

    tracker = CLIQuotaTracker()

    # 6a. Unknown provider returns defaults
    signals = tracker.get_adaptive_signals("unknown")
    check("unknown provider success_rate defaults to 1.0",
          signals["recent_success_rate"] == 1.0)
    check("unknown provider failure_rate defaults to 0.0",
          signals["recent_failure_rate"] == 0.0)
    check("unknown provider avg_execution_time defaults to 0.0",
          signals["avg_execution_time"] == 0.0)
    check("unknown provider is_available defaults to True",
          signals["is_available"] is True)
    check("unknown provider total_sessions defaults to 0",
          signals["total_sessions"] == 0)

    # 6b. After recording sessions, signals are correct
    tracker.record_session("sig_prov", duration_seconds=10.0)
    tracker.record_session("sig_prov", duration_seconds=20.0)
    signals = tracker.get_adaptive_signals("sig_prov")
    check("2 successes -> total_sessions == 2",
          signals["total_sessions"] == 2)
    check("2 successes -> success_rate == 1.0",
          signals["recent_success_rate"] == 1.0)
    check("2 successes -> failure_rate == 0.0",
          signals["recent_failure_rate"] == 0.0)
    check("avg_execution_time is (10+20)/2 = 15.0",
          signals["avg_execution_time"] == 15.0)

    # 6c. After recording successes and failures
    tracker.record_session("mixed_prov", duration_seconds=5.0)
    tracker.record_session("mixed_prov", duration_seconds=10.0)
    # Simulate 2 failures
    tracker._get_or_create("mixed_prov").recent_failure_count = 2
    signals_mixed = tracker.get_adaptive_signals("mixed_prov")
    check("2 success + 2 failure -> total_sessions == 4",
          signals_mixed["total_sessions"] == 4)
    check("2/4 success -> success_rate == 0.5",
          signals_mixed["recent_success_rate"] == 0.5)
    check("2/4 failure -> failure_rate == 0.5",
          signals_mixed["recent_failure_rate"] == 0.5)


# ===========================================================================
# 7. CLIQuotaTracker.get_provider_status()
# ===========================================================================

def test_cli_quota_tracker_provider_status():
    print("\n--- 7. CLIQuotaTracker.get_provider_status() ---")

    tracker = CLIQuotaTracker()

    # 7a. Unknown provider returns None
    status = tracker.get_provider_status("unknown_prov")
    check("unknown provider status is None",
          status is None)

    # 7b. Known provider returns dict with all fields
    tracker.record_session("status_prov", duration_seconds=3.0)
    tracker.check_available("status_prov")
    tracker.mark_blocked("status_prov", reason="test_error",
                         blocked_until=datetime.now(timezone.utc) + timedelta(hours=1))
    # After mark_blocked, status is "blocked". Let's reset and record fresh.
    tracker.reset("status_prov")
    tracker.record_session("status_prov", duration_seconds=5.0)
    tracker.check_available("status_prov")
    status = tracker.get_provider_status("status_prov")
    check("known provider status is a dict",
          isinstance(status, dict))
    check("status dict has 'provider' key", "provider" in status)
    check("status dict has 'status' key", "status" in status)
    check("status dict has 'session_count' key", "session_count" in status)
    check("status dict has 'last_health_check' key",
          "last_health_check" in status)
    check("status dict has 'last_error' key", "last_error" in status)

    # 7c. Includes adaptive signals in response
    check("status includes recent_success_rate",
          "recent_success_rate" in status)
    check("status includes recent_failure_rate",
          "recent_failure_rate" in status)
    check("status includes total_sessions",
          "total_sessions" in status)
    check("status includes is_available",
          "is_available" in status)
    check("status includes avg_execution_time",
          "avg_execution_time" in status)

    # 7d. Verify actual values
    check("provider name matches", status["provider"] == "status_prov")
    check("last_health_check is set",
          status["last_health_check"] is not None)
    check("last_error is None after reset",
          status["last_error"] is None)


# ===========================================================================
# 8. RoutingDecision new columns
# ===========================================================================

def test_routing_decision_columns():
    print("\n--- 8. RoutingDecision new columns ---")

    from app.models import RoutingDecision
    from sqlalchemy import inspect
    from sqlalchemy.orm import Mapper

    # Get the mapper for RoutingDecision
    mapper = inspect(RoutingDecision)
    column_names = {c.key for c in mapper.columns}

    # 8a. Verify new columns exist
    new_columns = [
        "task_complexity",
        "selected_cli_provider",
        "fallback_reason",
        "considered_providers",
        "rejected_providers",
    ]
    for col in new_columns:
        check(f"RoutingDecision has column '{col}'",
              col in column_names)

    # 8b. Verify nullable columns
    nullable_columns = [
        "task_complexity",
        "selected_cli_provider",
        "fallback_reason",
        "considered_providers",
        "rejected_providers",
    ]
    for col in nullable_columns:
        col_obj = mapper.columns[col]
        check(f"'{col}' is nullable",
              col_obj.nullable is True)


# ===========================================================================
# 9. System stats provider key
# ===========================================================================

def test_system_stats_importable():
    print("\n--- 9. System stats provider key ---")

    # 9a. Verify system_stats function is importable
    from app.api.system import system_stats
    check("system_stats is importable", callable(system_stats))

    # 9b. Verify it's an async function
    import asyncio
    check("system_stats is a coroutine function",
          asyncio.iscoroutinefunction(system_stats))


# ===========================================================================
# 10. decide() purity tests
# ===========================================================================

def test_decide_purity():
    print("\n--- 10. decide() purity ---")

    # 10a. lookup_cli_policy is importable and returns correct values
    check("lookup_cli_policy is importable",
          callable(lookup_cli_policy))

    # 10b. _CLI_ROUTING_POLICY has expected entries
    check("_CLI_ROUTING_POLICY is a dict",
          isinstance(_CLI_ROUTING_POLICY, dict))
    check("_CLI_ROUTING_POLICY has code_gen+complex entry",
          ("code_gen", "complex") in _CLI_ROUTING_POLICY)
    check("_CLI_ROUTING_POLICY has code_gen+simple entry",
          ("code_gen", "simple") in _CLI_ROUTING_POLICY)
    check("_CLI_ROUTING_POLICY has analysis+complex entry",
          ("analysis", "complex") in _CLI_ROUTING_POLICY)

    # 10c. _CLI_DEFAULT_ORDER is defined
    check("_CLI_DEFAULT_ORDER is defined",
          isinstance(_CLI_DEFAULT_ORDER, list))
    check("_CLI_DEFAULT_ORDER has claude_code",
          "claude_code" in _CLI_DEFAULT_ORDER)

    # 10d. Verify policy values are correct
    check("code_gen+complex policy value correct",
          _CLI_ROUTING_POLICY[("code_gen", "complex")] == ["claude_code", "glm_coding"])
    check("code_gen+simple policy value correct",
          _CLI_ROUTING_POLICY[("code_gen", "simple")] == ["glm_coding", "claude_code"])
    check("analysis+complex policy value correct",
          _CLI_ROUTING_POLICY[("analysis", "complex")] == ["claude_code"])

    # 10e. _reorder_by_adaptive_signals uses correct threshold values
    # We verify by checking the docstring references the thresholds
    router = _make_router()
    reorder_doc = router._reorder_by_adaptive_signals.__doc__
    check("_reorder references failure_rate > 0.5 threshold",
          reorder_doc is not None and "0.5" in reorder_doc)
    check("_reorder references failure_rate > 0.2 threshold",
          reorder_doc is not None and "0.2" in reorder_doc)
    check("_reorder references success_rate > 0.8 threshold",
          reorder_doc is not None and "0.8" in reorder_doc)

    # 10f. Verify _reorder actually deprioritizes failing providers
    # Create a tracker with failing provider and a healthy one
    router2 = _make_router()
    # Set up failure data for claude_code
    usage = router2._cli_quota._get_or_create("claude_code")
    usage.recent_success_count = 1
    usage.recent_failure_count = 5  # 5/6 = 83% failure, well above 0.5

    order = router2._reorder_by_adaptive_signals(
        ["claude_code", "glm_coding"], "code_gen", "simple"
    )
    check("_reorder deprioritizes high-failure provider",
          order[-1] == "claude_code")  # should be last due to high failure penalty

    # 10g. Verify _reorder boosts successful providers
    # Give both providers data so we can see the boost effect:
    #   claude_code: 3 successes, 2 failures (60% success, 40% failure -> +15 penalty)
    #     base_score=0, failure_penalty=15, total=15
    #   glm_coding: 10 successes, 0 failures (100% success -> -10 boost)
    #     base_score=10, success_boost=10, total=0
    # Result: glm_coding (0) < claude_code (15) -> glm_coding first
    router3 = _make_router()
    usage_cc = router3._cli_quota._get_or_create("claude_code")
    usage_cc.recent_success_count = 3
    usage_cc.recent_failure_count = 2
    usage_cc.status = "available"
    usage_gc = router3._cli_quota._get_or_create("glm_coding")
    usage_gc.recent_success_count = 10
    usage_gc.recent_failure_count = 0
    usage_gc.status = "available"

    order2 = router3._reorder_by_adaptive_signals(
        ["claude_code", "glm_coding"], "code_gen", "simple"
    )
    check("_reorder boosts high-success provider over moderate-failure provider",
          order2[0] == "glm_coding")  # score 0 < 15, so glm_coding first


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 60)
    print("Phase 5.6: Smart Routing Test Suite")
    print("=" * 60)

    test_context_optimizer()
    test_routing_policy_lookup()
    test_model_selection_by_complexity()
    test_cli_quota_tracker_enriched_fields()
    test_cli_quota_tracker_is_available()
    test_cli_quota_tracker_adaptive_signals()
    test_cli_quota_tracker_provider_status()
    test_routing_decision_columns()
    test_system_stats_importable()
    test_decide_purity()

    print("\n" + "=" * 60)
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed:
        print("\nFailed tests:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name} {detail}")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
