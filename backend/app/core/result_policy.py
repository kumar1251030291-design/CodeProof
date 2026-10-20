"""Shared candidate-facing result visibility rules."""

from app.models import Assessment, AssessmentAttempt


def candidate_result_is_visible(assessment: Assessment | None, attempt: AssessmentAttempt) -> bool:
    """Match the candidate attempt API's score disclosure policy exactly."""
    return bool(
        assessment
        and assessment.show_results_after_submission
        and attempt.status == "submitted"
        and attempt.review_status in {"complete", "not_required"}
        and attempt.final_score is not None
    )
