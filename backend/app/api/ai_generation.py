"""Authenticated endpoints for creating unsaved AI question suggestions."""

from fastapi import APIRouter, Depends, HTTPException

from app.ai.question_drafts import (
    GeneratedAssessment,
    GenerationRequest,
    OpenAIQuestionDraftProvider,
    ProviderMalformedOutput,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderTimedOut,
    ProviderUnavailable,
    QuestionDraftProvider,
    parse_generated_assessment,
)
from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.authorization import require_evaluator
from app.ai.rate_limit import ProcessLocalRateLimiter, RateLimitExceeded

router = APIRouter(prefix="/api/v1/evaluator/ai", tags=["evaluator AI drafts"])
ai_generation_limiter = ProcessLocalRateLimiter(limit=5, window_seconds=60)


def get_question_draft_provider() -> QuestionDraftProvider:
    return OpenAIQuestionDraftProvider()


@router.post("/question-drafts", response_model=GeneratedAssessment)
def generate_question_draft(
    data: GenerationRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    provider: QuestionDraftProvider = Depends(get_question_draft_provider),
) -> GeneratedAssessment:
    """Return validated suggestions only; this endpoint has no persistence path."""
    require_evaluator(identity)
    try:
        ai_generation_limiter.check(identity.profile.id)
        raw = provider.generate(data)
        return parse_generated_assessment(raw, data)
    except RateLimitExceeded as error:
        raise HTTPException(
            status_code=429,
            detail="AI draft request limit reached; try again later",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from None
    except ProviderNotConfigured:
        raise HTTPException(status_code=503, detail="AI draft generation is not configured") from None
    except ProviderRateLimited:
        raise HTTPException(status_code=429, detail="AI provider is rate limited; try again later") from None
    except ProviderTimedOut:
        raise HTTPException(status_code=504, detail="AI draft generation timed out") from None
    except ProviderMalformedOutput:
        raise HTTPException(status_code=502, detail="AI provider returned an invalid draft") from None
    except ProviderUnavailable:
        raise HTTPException(status_code=502, detail="AI draft generation is temporarily unavailable") from None
