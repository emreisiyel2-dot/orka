"""Light feedback service — processes completed runs for quality scores."""

from dataclasses import dataclass

from app.models import Run, RoutingDecision


@dataclass
class RunFeedback:
    run_id: str
    success: bool
    quality_score: float
    failure_classification: str | None


class FeedbackService:

    def process_run(
        self,
        run: Run,
        decision: RoutingDecision | None = None,
    ) -> RunFeedback:
        success = run.status == "completed"
        return RunFeedback(
            run_id=run.id,
            success=success,
            quality_score=1.0 if success else 0.0,
            failure_classification=run.failure_type,
        )
