"""Candidate-only AI assistance scoped to the active authenticated attempt."""

from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.candidate_assistant import (
    MAX_REQUEST_BODY_BYTES,
    MAX_PROVIDER_OUTPUT_CHARS,
    AssistantMalformedOutput,
    AssistantNotConfigured,
    AssistantRateLimited,
    AssistantTimedOut,
    AssistantUnavailable,
    CandidateAssistantProvider,
    CandidateQuestionContext,
    GeminiCandidateAssistant,
)
from app.ai.rate_limit import ProcessLocalRateLimiter, RateLimitExceeded
from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.authorization import require_candidate
from app.core.database import get_db_session
from app.models import AssessmentAttempt, Question
from app.schemas.candidate_assistant import (
    CandidateAssistanceRequest,
    CandidateAssistanceResponse,
)


class BoundedBodyRoute(APIRoute):
    """Reject oversized bodies before FastAPI parses the JSON payload."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def bounded_handler(request: Request):
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_REQUEST_BODY_BYTES:
                    return JSONResponse(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        content={"detail": "AI assistance request is too large"},
                    )
                body.extend(chunk)
            request._body = bytes(body)
            return await original_handler(request)

        return bounded_handler


router = APIRouter(
    prefix="/api/v1/candidate/ai",
    tags=["candidate AI assistance"],
    route_class=BoundedBodyRoute,
)
candidate_assistance_limiter = ProcessLocalRateLimiter(limit=5, window_seconds=60)


def get_candidate_assistant_provider() -> CandidateAssistantProvider:
    return GeminiCandidateAssistant()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@router.post("/assistance", response_model=CandidateAssistanceResponse)
def candidate_assistance(
    data: CandidateAssistanceRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
    provider: CandidateAssistantProvider = Depends(get_candidate_assistant_provider),
) -> CandidateAssistanceResponse:
    """Answer a candidate question without reading test cases or changing state."""
    require_candidate(identity)

    attempt = session.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.id == data.attempt_id,
            AssessmentAttempt.assessment_id == data.assessment_id,
            AssessmentAttempt.candidate_id == identity.profile.id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.status != "in_progress":
        raise HTTPException(status_code=409, detail="AI assistance is available only during an active attempt")
    if _utc(attempt.deadline_at) <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="AI assistance is unavailable after the attempt deadline")

    question = session.scalar(
        select(Question).where(
            Question.id == data.question_id,
            Question.assessment_id == attempt.assessment_id,
        )
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    try:
        candidate_assistance_limiter.check(identity.profile.id)
        answer = provider.respond(
            CandidateQuestionContext(
                title=question.title,
                prompt=question.prompt,
                problem_statement=question.problem_statement,
                examples=question.examples,
                question_type=question.question_type,
                allowed_languages=tuple(question.allowed_languages or []),
            ),
            data,
        )
        if not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_PROVIDER_OUTPUT_CHARS:
            raise AssistantMalformedOutput
        return CandidateAssistanceResponse(message=answer)
    except RateLimitExceeded as error:
        raise HTTPException(
            status_code=429,
            detail="AI assistance request limit reached; try again later",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from None
    except AssistantNotConfigured:
        raise HTTPException(status_code=503, detail="Candidate AI assistance is not configured") from None
    except AssistantRateLimited:
        raise HTTPException(status_code=429, detail="AI provider is rate limited; try again later") from None
    except AssistantTimedOut:
        raise HTTPException(status_code=504, detail="AI assistance timed out; try again") from None
    except AssistantMalformedOutput:
        raise HTTPException(status_code=502, detail="AI provider returned an invalid response") from None
    except AssistantUnavailable:
        raise HTTPException(status_code=502, detail="AI assistance is temporarily unavailable") from None
