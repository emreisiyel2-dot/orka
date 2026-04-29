"""Basic retry intelligence — simple rules to decide if a failed run should be retried."""

from dataclasses import dataclass

from app.models import Run


@dataclass
class RetryEvaluation:
    eligible: bool
    reason: str
    strategy: str  # "same_provider" | "alternate_provider" | "none"
    max_retries: int


class RetryIntelligence:

    def evaluate(self, run: Run) -> RetryEvaluation:
        if run.retry_count >= 2:
            return RetryEvaluation(
                eligible=False,
                reason="max retries reached",
                strategy="none",
                max_retries=0,
            )

        ftype = run.failure_type

        if ftype == "validation_failed":
            return RetryEvaluation(
                eligible=False,
                reason="fix code, don't retry",
                strategy="none",
                max_retries=0,
            )

        if ftype == "timeout":
            return RetryEvaluation(
                eligible=True,
                reason="retry once after timeout",
                strategy="same_provider",
                max_retries=1,
            )

        if ftype == "cli_error":
            return RetryEvaluation(
                eligible=True,
                reason="retry with alternate CLI provider",
                strategy="alternate_provider",
                max_retries=1,
            )

        if ftype == "model_error":
            return RetryEvaluation(
                eligible=True,
                reason="retry with alternate provider",
                strategy="alternate_provider",
                max_retries=1,
            )

        return RetryEvaluation(
            eligible=True,
            reason="generic retry",
            strategy="same_provider",
            max_retries=1,
        )
