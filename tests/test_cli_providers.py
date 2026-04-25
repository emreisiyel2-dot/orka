"""
CLI Providers Unit Tests

Run from backend dir:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_cli_providers.py
"""
import asyncio
import sys
import os

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Disable LLM and CLI so config loads cleanly without keys
os.environ.setdefault("ORKA_LLM_ENABLED", "false")
os.environ.setdefault("ORKA_CLI_ENABLED", "false")

from app.providers.cli_process import (
    CLIExecutionResult,
    check_prompt,
    check_rate_limit,
    execute_cli,
)
from app.providers.cli_claude import ClaudeCodeCLIProvider
from app.providers.cli_glm import GLMCodingCLIProvider
from app.services.cli_quota_tracker import CLIQuotaTracker
from app.services.model_router import classify_task
from app.config.model_config import load_config
from app.providers.registry import ProviderRegistry

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


async def run_tests():

    # ── Test 1: CLIExecutionResult ─────────────────────────
    print("=" * 60)
    print("TEST 1: CLIExecutionResult")
    print("=" * 60)
    r = CLIExecutionResult(
        exit_code=0, stdout="hello", stderr="", duration_seconds=0.1,
        timed_out=False,
    )
    ok = r.exit_code == 0 and r.stdout == "hello" and r.timed_out is False
    print(f"  exit_code={r.exit_code}, stdout={r.stdout!r}, timed_out={r.timed_out}")
    results.append(("CLIExecutionResult", PASS if ok else FAIL, f"exit={r.exit_code} stdout={r.stdout!r} timed_out={r.timed_out}"))

    # ── Test 2: check_prompt safe ───────────────────────────
    print()
    print("=" * 60)
    print("TEST 2: check_prompt (safe)")
    print("=" * 60)
    safe_cases = [
        ("Do you want to continue? [y/N]", True, "y\n"),
        ("Press Enter to continue", True, "\n"),
        ("Continue? [y/n]", True, "y\n"),
        ("Building project...", False, None),
    ]
    all_safe_ok = True
    for line, expect_prompt, expect_auto in safe_cases:
        is_prompt, auto_response, input_type, reason = check_prompt(line)
        ok = is_prompt == expect_prompt and auto_response == expect_auto
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status:7s}] {line!r:45s} → is_prompt={is_prompt}, auto={auto_response!r}")
        if not ok:
            all_safe_ok = False
    results.append(("check_prompt (safe)", PASS if all_safe_ok else FAIL, f"{len(safe_cases)} cases"))

    # ── Test 3: check_prompt critical ───────────────────────
    print()
    print("=" * 60)
    print("TEST 3: check_prompt (critical)")
    print("=" * 60)
    critical_cases = [
        "delete permanent",
        "password:",
        "deploy prod",
    ]
    all_critical_ok = True
    for line in critical_cases:
        is_prompt, auto_response, input_type, reason = check_prompt(line)
        ok = is_prompt is True and auto_response is None
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status:7s}] {line!r:35s} → auto_response={auto_response}, reason={reason}")
        if not ok:
            all_critical_ok = False
    results.append(("check_prompt (critical)", PASS if all_critical_ok else FAIL, f"{len(critical_cases)} cases"))

    # ── Test 4: check_rate_limit ────────────────────────────
    print()
    print("=" * 60)
    print("TEST 4: check_rate_limit")
    print("=" * 60)
    rl_cases = [
        ("rate limit exceeded", True),
        ("quota exceeded for this plan", True),
        ("normal output", False),
    ]
    all_rl_ok = True
    for line, expect_detected in rl_cases:
        reason = check_rate_limit(line)
        detected = reason is not None
        ok = detected == expect_detected
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status:7s}] {line!r:40s} → detected={detected}, reason={reason}")
        if not ok:
            all_rl_ok = False
    results.append(("check_rate_limit", PASS if all_rl_ok else FAIL, f"{len(rl_cases)} cases"))

    # ── Test 5: execute_cli with echo ───────────────────────
    print()
    print("=" * 60)
    print("TEST 5: execute_cli (echo)")
    print("=" * 60)
    echo_result = await execute_cli(["echo", "hello world"], timeout=5.0)
    ok = echo_result.exit_code == 0 and "hello world" in echo_result.stdout
    print(f"  exit_code={echo_result.exit_code}, stdout={echo_result.stdout!r}, timed_out={echo_result.timed_out}")
    results.append(("execute_cli (echo)", PASS if ok else FAIL, f"exit={echo_result.exit_code}, stdout={echo_result.stdout!r}"))

    # ── Test 6: execute_cli with timeout ────────────────────
    print()
    print("=" * 60)
    print("TEST 6: execute_cli (timeout)")
    print("=" * 60)
    timeout_result = await execute_cli(["bash", "-c", "exec 1>&- 2>&-; sleep 10"], timeout=1.0)
    ok = timeout_result.timed_out is True
    print(f"  exit_code={timeout_result.exit_code}, timed_out={timeout_result.timed_out}, duration={timeout_result.duration_seconds:.2f}s")
    results.append(("execute_cli (timeout)", PASS if ok else FAIL, f"timed_out={timeout_result.timed_out}"))

    # ── Test 7: ClaudeCodeCLIProvider build_command ─────────
    print()
    print("=" * 60)
    print("TEST 7: ClaudeCodeCLIProvider build_command")
    print("=" * 60)
    claude = ClaudeCodeCLIProvider(binary="claude")
    cmd = claude.build_command("fix the bug", "claude-sonnet-4-6")
    has_print = "--print" in cmd
    has_p = "-p" in cmd
    has_prompt = "fix the bug" in cmd
    ok = has_print and has_p and has_prompt
    print(f"  command={cmd}")
    print(f"  --print={has_print}, -p={has_p}, prompt_in_cmd={has_prompt}")
    results.append(("ClaudeCodeCLIProvider build_command", PASS if ok else FAIL, f"cmd={cmd}"))

    # ── Test 8: ClaudeCodeCLIProvider parse_output ──────────
    print()
    print("=" * 60)
    print("TEST 8: ClaudeCodeCLIProvider parse_output")
    print("=" * 60)
    json_resp = claude.parse_output('{"result":"fixed!"}', "claude-sonnet-4-6")
    raw_resp = claude.parse_output("plain text output", "claude-sonnet-4-6")
    json_ok = json_resp.content == "fixed!"
    raw_ok = raw_resp.content == "plain text output"
    ok = json_ok and raw_ok
    print(f"  JSON parse: content={json_resp.content!r} (ok={json_ok})")
    print(f"  Raw fallback: content={raw_resp.content!r} (ok={raw_ok})")
    results.append(("ClaudeCodeCLIProvider parse_output", PASS if ok else FAIL, f"json_ok={json_ok}, raw_ok={raw_ok}"))

    # ── Test 9: GLMCodingCLIProvider build_command ──────────
    print()
    print("=" * 60)
    print("TEST 9: GLMCodingCLIProvider build_command")
    print("=" * 60)
    glm = GLMCodingCLIProvider(binary="glm")
    cmd = glm.build_command("implement feature X", "glm-4-plus")
    has_model = "--model" in cmd
    has_prompt = "implement feature X" in cmd
    ok = has_model and has_prompt
    print(f"  command={cmd}")
    print(f"  --model={has_model}, prompt_in_cmd={has_prompt}")
    results.append(("GLMCodingCLIProvider build_command", PASS if ok else FAIL, f"cmd={cmd}"))

    # ── Test 10: CLIQuotaTracker lifecycle ──────────────────
    print()
    print("=" * 60)
    print("TEST 10: CLIQuotaTracker lifecycle")
    print("=" * 60)
    tracker = CLIQuotaTracker(max_concurrent=2, max_sessions_per_hour=5, throttle_threshold=0.2)
    p = "test_provider"
    lifecycle_ok = True
    checks = []

    # available
    s = tracker.check_available(p)
    checks.append(("available (initial)", s == "available", s))

    # record 4 sessions → remaining=1 <= threshold(1) → throttled
    for i in range(4):
        tracker.record_session(p, duration_seconds=1.0)
    s = tracker.check_available(p)
    checks.append(("throttled (4 sessions)", s == "throttled", s))
    if s != "throttled":
        lifecycle_ok = False

    # record 1 more → session_count=5 >= max(5) → blocked
    tracker.record_session(p, duration_seconds=1.0)
    s = tracker.check_available(p)
    checks.append(("blocked (5 sessions)", s == "blocked", s))
    if s != "blocked":
        lifecycle_ok = False

    # reset → available again
    tracker.reset(p)
    s = tracker.check_available(p)
    checks.append(("available (after reset)", s == "available", s))
    if s != "available":
        lifecycle_ok = False

    # start 2 sessions → at max_concurrent(2) → throttled
    tracker.start_session(p)
    tracker.start_session(p)
    s = tracker.check_available(p)
    checks.append(("throttled (2 concurrent)", s == "throttled", s))
    if s != "throttled":
        lifecycle_ok = False

    # end 1 session → 1 active < max_concurrent(2) → available
    tracker.end_session(p)
    s = tracker.check_available(p)
    checks.append(("available (1 concurrent ended)", s == "available", s))
    if s != "available":
        lifecycle_ok = False

    for label, passed, actual in checks:
        status = "OK" if passed else "MISMATCH"
        print(f"  [{status:7s}] {label:35s} → {actual}")
    results.append(("CLIQuotaTracker lifecycle", PASS if lifecycle_ok else FAIL, f"{len(checks)} steps"))

    # ── Test 11: classify_task with execution_mode ──────────
    print()
    print("=" * 60)
    print("TEST 11: classify_task with execution_mode")
    print("=" * 60)
    em_cases = [
        ("fix the login bug", "coding", "normal", True, "cli"),
        ("write api documentation", "docs", "normal", True, "api"),
        ("fix the login bug", "coding", "normal", False, "api"),
    ]
    all_em_ok = True
    for content, agent, importance, has_cli, expected_mode in em_cases:
        profile = classify_task(content, agent, importance, has_cli_providers=has_cli)
        ok = profile.execution_mode == expected_mode
        status = "OK" if ok else "MISMATCH"
        print(f"  [{status:7s}] agent={agent:8s} has_cli={has_cli!s:5s} → mode={profile.execution_mode} (expected={expected_mode})")
        if not ok:
            all_em_ok = False
    results.append(("classify_task execution_mode", PASS if all_em_ok else FAIL, f"{len(em_cases)} cases"))

    # ── Test 12: CLIConfig ──────────────────────────────────
    print()
    print("=" * 60)
    print("TEST 12: CLIConfig")
    print("=" * 60)
    config = load_config()
    cli_disabled = config.cli_enabled is False
    has_cli_providers = len(config.cli_providers) >= 2
    ok = cli_disabled and has_cli_providers
    print(f"  cli_enabled={config.cli_enabled} (expected False, ok={cli_disabled})")
    print(f"  cli_providers count={len(config.cli_providers)} (expected >=2, ok={has_cli_providers})")
    names = [cp.name for cp in config.cli_providers]
    print(f"  cli_provider names={names}")
    results.append(("CLIConfig", PASS if ok else FAIL, f"cli_enabled={config.cli_enabled}, providers={len(config.cli_providers)}"))

    # ── Test 13: Registry with CLI disabled ─────────────────
    print()
    print("=" * 60)
    print("TEST 13: Registry with CLI disabled")
    print("=" * 60)
    registry = ProviderRegistry(config)
    has_cli = registry.has_cli_providers()
    cli_list = registry.all_by_mode()["cli"]
    ok = has_cli is False and len(cli_list) == 0
    print(f"  has_cli_providers()={has_cli} (expected False, ok={has_cli is False})")
    print(f"  cli providers list={cli_list} (expected empty, ok={len(cli_list) == 0})")
    results.append(("Registry with CLI disabled", PASS if ok else FAIL, f"has_cli={has_cli}, cli_list_len={len(cli_list)}"))

    # ── SUMMARY ─────────────────────────────────────────────
    print()
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    for name, status, detail in results:
        print(f"  [{status:4s}] {name:40s}: {detail}")

    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    print(f"\n  {passed} passed, {failed} failed out of {len(results)} tests")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
