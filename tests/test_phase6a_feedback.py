"""
Phase 6A: FeedbackService Tests

Validates:
1. Successful run → success=True, quality_score=1.0
2. Failed run → success=False, quality_score=0.0
3. Failure classification maps from run.failure_type
4. Works with None decision (backward compat)

Run:
    cd backend && source venv/bin/activate
    PYTHONPATH=$(pwd) python3 ../tests/test_phase6a_feedback.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.feedback_service import FeedbackService

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "OK" if ok else "FAIL"
    print(f"  [{status:4s}] {name} {detail}")


class MockRun:
    def __init__(self, run_id="r-1", status="completed", failure_type=None):
        self.id = run_id
        self.status = status
        self.failure_type = failure_type


def test_successful_run():
    svc = FeedbackService()
    fb = svc.process_run(MockRun("r-1", "completed"))
    check("success flag", fb.success is True)
    check("quality_score 1.0", fb.quality_score == 1.0, f"got {fb.quality_score}")
    check("failure_classification None", fb.failure_classification is None)
    check("run_id preserved", fb.run_id == "r-1")


def test_failed_run():
    svc = FeedbackService()
    fb = svc.process_run(MockRun("r-2", "failed", "timeout"))
    check("success flag False", fb.success is False)
    check("quality_score 0.0", fb.quality_score == 0.0, f"got {fb.quality_score}")
    check("failure_classification timeout", fb.failure_classification == "timeout")


def test_failure_types():
    svc = FeedbackService()
    for ftype in ("timeout", "quota_block", "model_error", "cli_error", "validation_failed"):
        fb = svc.process_run(MockRun(f"r-{ftype}", "failed", ftype))
        check(f"classification {ftype}", fb.failure_classification == ftype)


def test_none_decision():
    svc = FeedbackService()
    fb = svc.process_run(MockRun("r-3", "completed"), decision=None)
    check("works with None decision", fb.success is True)


def main():
    print("=" * 60)
    print("Phase 6A: FeedbackService Tests")
    print("=" * 60)

    test_successful_run()
    print()
    test_failed_run()
    print()
    test_failure_types()
    print()
    test_none_decision()

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Results: {passed}/{len(results)} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
