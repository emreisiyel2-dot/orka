"""
Phase 6A: RetryIntelligence Tests

Validates:
1. Max retries reached (retry_count >= 2) → not eligible
2. validation_failed → not eligible
3. timeout → eligible, same_provider
4. cli_error → eligible, alternate_provider
5. model_error → eligible, alternate_provider
6. Unknown failure → eligible, same_provider
7. max_retries always 1
8. None failure_type → eligible, same_provider

Run:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_phase6a_retry.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.retry_intelligence import RetryIntelligence

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {name} {detail}")


class MockRun:
    def __init__(self, retry_count=0, failure_type=None):
        self.retry_count = retry_count
        self.failure_type = failure_type


def test_max_retries():
    svc = RetryIntelligence()
    r = svc.evaluate(MockRun(retry_count=2, failure_type="timeout"))
    check("retry_count=2 not eligible", not r.eligible)
    check("reason max retries", r.reason == "max retries reached")
    check("strategy none", r.strategy == "none")
    check("max_retries 0", r.max_retries == 0)

    r3 = svc.evaluate(MockRun(retry_count=3, failure_type="timeout"))
    check("retry_count=3 not eligible", not r3.eligible)


def test_validation_failed():
    svc = RetryIntelligence()
    r = svc.evaluate(MockRun(retry_count=0, failure_type="validation_failed"))
    check("validation_failed not eligible", not r.eligible)
    check("reason fix code", "fix code" in r.reason)


def test_timeout():
    svc = RetryIntelligence()
    r = svc.evaluate(MockRun(retry_count=0, failure_type="timeout"))
    check("timeout eligible", r.eligible)
    check("strategy same_provider", r.strategy == "same_provider")
    check("max_retries 1", r.max_retries == 1)


def test_cli_error():
    svc = RetryIntelligence()
    r = svc.evaluate(MockRun(retry_count=0, failure_type="cli_error"))
    check("cli_error eligible", r.eligible)
    check("strategy alternate_provider", r.strategy == "alternate_provider")


def test_model_error():
    svc = RetryIntelligence()
    r = svc.evaluate(MockRun(retry_count=0, failure_type="model_error"))
    check("model_error eligible", r.eligible)
    check("strategy alternate_provider", r.strategy == "alternate_provider")


def test_unknown_failure():
    svc = RetryIntelligence()
    r = svc.evaluate(MockRun(retry_count=0, failure_type="weird_error"))
    check("unknown failure eligible", r.eligible)
    check("strategy same_provider", r.strategy == "same_provider")
    check("reason generic", r.reason == "generic retry")


def test_none_failure_type():
    svc = RetryIntelligence()
    r = svc.evaluate(MockRun(retry_count=0, failure_type=None))
    check("None failure_type eligible", r.eligible)
    check("strategy same_provider", r.strategy == "same_provider")


def test_max_retries_is_always_1():
    svc = RetryIntelligence()
    for ftype in ("timeout", "cli_error", "model_error", "quota_block", None):
        r = svc.evaluate(MockRun(retry_count=0, failure_type=ftype))
        if r.eligible:
            check(f"max_retries=1 for {ftype}", r.max_retries == 1, f"got {r.max_retries}")


def main():
    print("=" * 60)
    print("Phase 6A: RetryIntelligence Tests")
    print("=" * 60)

    test_max_retries()
    print()
    test_validation_failed()
    print()
    test_timeout()
    print()
    test_cli_error()
    print()
    test_model_error()
    print()
    test_unknown_failure()
    print()
    test_none_failure_type()
    print()
    test_max_retries_is_always_1()

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Results: {passed}/{len(results)} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
