"""Candidate follow-up interview and owner-authorized evaluator review."""

import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.rate_limit import ProcessLocalRateLimiter, RateLimitExceeded
from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.authorization import get_owned_assessment, require_candidate
from app.core.config import settings
from app.core.database import get_db_session
from app.models import AssessmentAttempt, AttemptResponse, FollowUpInterview, FollowUpQuestion, Question

router = APIRouter(tags=["follow-up interviews"])
generation_limiter = ProcessLocalRateLimiter(limit=3, window_seconds=300)
question_limiter = ProcessLocalRateLimiter(limit=10, window_seconds=300)
MAX_AI_QUESTIONS = 5
MAX_TOTAL_QUESTIONS = 20


class AnswerInput(BaseModel):
    answer: str = Field(max_length=20000)


class EvaluatorQuestionInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class ReviewInput(BaseModel):
    notes: str = Field(default="", max_length=10000)
    score: int | None = Field(default=None, ge=0, le=100)


class GeneratedQuestions(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=MAX_AI_QUESTIONS)


def _generate_questions(payload: dict[str, object]) -> list[str]:
    instructions = f"Generate exactly {settings.follow_up_question_count} concise, relevant technical follow-up interview questions based only on the supplied assessment prompt and candidate submission. Address reasoning, algorithm choice, complexity, edge cases, testing, or improvements; for debugging tasks ask about diagnosis and root cause. Do not claim tests passed unless the supplied execution summary says so. Return only JSON with a questions array of strings."
    provider = settings.ai_provider.lower()
    if provider == "openai":
        if not settings.openai_api_key:
            raise HTTPException(status_code=503, detail="Follow-up question generation is not configured")
        body = {"model": settings.ai_model, "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "response_format": {"type": "json_object"}, "store": False}
        request = Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}, method="POST")
    elif provider == "gemini":
        if not settings.gemini_api_key:
            raise HTTPException(status_code=503, detail="Follow-up question generation is not configured")
        body = {"system_instruction": {"parts": [{"text": instructions}]}, "contents": [{"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}], "generationConfig": {"responseMimeType": "application/json"}}
        request = Request(f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": settings.gemini_api_key}, method="POST")
    else:
        raise HTTPException(status_code=503, detail="Follow-up question generation is not configured")
    try:
        with urlopen(request, timeout=max(5, min(settings.ai_timeout_seconds, 60))) as response:
            raw = response.read(100_001)
    except HTTPError as error:
        raise HTTPException(status_code=502 if error.code != 429 else 503, detail="AI question generation is temporarily unavailable") from None
    except (URLError, TimeoutError, OSError):
        raise HTTPException(status_code=502, detail="AI question generation is temporarily unavailable") from None
    if len(raw) > 100_000:
        raise HTTPException(status_code=502, detail="AI provider returned an invalid response")
    try:
        envelope = json.loads(raw)
        content = envelope["choices"][0]["message"]["content"] if provider == "openai" else envelope["candidates"][0]["content"]["parts"][0]["text"]
        questions = GeneratedQuestions.model_validate_json(content).questions
    except (ValueError, KeyError, TypeError, IndexError, ValidationError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail="AI provider returned invalid follow-up questions") from None
    cleaned = [item.strip() for item in questions]
    if len(cleaned) != settings.follow_up_question_count or any(not item or len(item) > 1000 for item in cleaned) or len({q.casefold() for q in cleaned}) != len(cleaned):
        raise HTTPException(status_code=502, detail="AI provider returned invalid follow-up questions")
    return cleaned


def _interview_data(session: Session, interview: FollowUpInterview, *, private: bool) -> dict[str, object]:
    items = session.scalars(select(FollowUpQuestion).where(FollowUpQuestion.interview_id == interview.id).order_by(FollowUpQuestion.created_at, FollowUpQuestion.id)).all()
    return {
        "id": str(interview.id), "attempt_id": str(interview.attempt_id), "assessment_id": str(interview.assessment_id),
        "status": interview.status, "submitted_at": interview.submitted_at, "reviewed_at": interview.reviewed_at if private else None,
        "reviewer_id": str(interview.reviewer_id) if private and interview.reviewer_id else None,
        "review_notes": interview.review_notes if private else None, "review_score": interview.review_score if private else None,
        "questions": [{"id": str(q.id), "prompt": q.prompt, "origin": q.origin, "answer": q.answer,
                       "answered_at": q.answered_at, "answer_locked": q.answer_locked,
                       "created_at": q.created_at} for q in items],
    }


def _candidate_interview(session: Session, attempt_id: UUID, identity: AuthenticatedIdentity, *, lock: bool = False) -> tuple[AssessmentAttempt, FollowUpInterview]:
    query = select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id, AssessmentAttempt.candidate_id == identity.profile.id)
    if lock:
        query = query.with_for_update()
    attempt = session.scalar(query)
    if attempt is None or attempt.status != "submitted":
        raise HTTPException(status_code=404, detail="Submitted attempt not found")
    interview = session.scalar(select(FollowUpInterview).where(FollowUpInterview.attempt_id == attempt.id))
    if interview is None:
        raise HTTPException(status_code=404, detail="Follow-up interview is not available yet")
    return attempt, interview


@router.post("/api/v1/candidate/attempts/{attempt_id}/follow-up/generate")
def generate_interview(attempt_id: UUID, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db_session)):
    require_candidate(identity)
    attempt = session.scalar(select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id, AssessmentAttempt.candidate_id == identity.profile.id).with_for_update())
    if attempt is None or attempt.status != "submitted":
        raise HTTPException(status_code=404, detail="Submitted attempt not found")
    interview = session.scalar(select(FollowUpInterview).where(FollowUpInterview.attempt_id == attempt.id).with_for_update())
    if interview and session.scalar(select(FollowUpQuestion.id).where(FollowUpQuestion.interview_id == interview.id).limit(1)):
        session.commit()
        return _interview_data(session, interview, private=False)
    try:
        generation_limiter.check(identity.profile.id)
    except RateLimitExceeded as error:
        session.rollback()
        raise HTTPException(status_code=429, detail="Follow-up generation limit reached; try again later", headers={"Retry-After": str(error.retry_after_seconds)}) from None
    assessment_questions = session.scalars(select(Question).where(Question.assessment_id == attempt.assessment_id)).all()
    submitted = session.scalars(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)).all()
    by_id = {item.question_id: item for item in submitted}
    # Only visible assessment content and this candidate's own answer enter the provider request.
    context = [{"assessment_question": q.prompt, "question_type": q.question_type,
                "submission": by_id[q.id].response_text if q.id in by_id else "",
                "language": by_id[q.id].programming_language if q.id in by_id else None,
                "execution_status": by_id[q.id].execution_status if q.id in by_id else "unavailable",
                "execution_summary": (f"{by_id[q.id].passed_test_cases}/{by_id[q.id].total_test_cases} test cases passed"
                                      if q.id in by_id and by_id[q.id].passed_test_cases is not None and by_id[q.id].total_test_cases is not None
                                      else "No detailed execution results available")} for q in assessment_questions]
    prompts = _generate_questions({"questions": context})
    if interview is None:
        interview = FollowUpInterview(attempt_id=attempt.id, assessment_id=attempt.assessment_id, candidate_id=attempt.candidate_id, status="in_progress")
        session.add(interview)
        session.flush()
    for prompt in prompts:
        session.add(FollowUpQuestion(interview_id=interview.id, prompt=prompt, origin="ai"))
    session.commit()
    return _interview_data(session, interview, private=False)


@router.get("/api/v1/candidate/attempts/{attempt_id}/follow-up")
def get_candidate_interview(attempt_id: UUID, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db_session)):
    require_candidate(identity)
    _, interview = _candidate_interview(session, attempt_id, identity)
    return _interview_data(session, interview, private=False)


@router.put("/api/v1/candidate/attempts/{attempt_id}/follow-up/questions/{question_id}")
def save_interview_answer(attempt_id: UUID, question_id: UUID, data: AnswerInput, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db_session)):
    require_candidate(identity)
    attempt, interview = _candidate_interview(session, attempt_id, identity, lock=True)
    question = session.scalar(select(FollowUpQuestion).where(FollowUpQuestion.id == question_id, FollowUpQuestion.interview_id == interview.id).with_for_update())
    if question is None:
        raise HTTPException(status_code=404, detail="Interview question not found")
    if question.answer_locked:
        raise HTTPException(status_code=409, detail="This submitted answer is locked")
    question.answer = data.answer
    question.answered_at = datetime.now(UTC) if data.answer.strip() else None
    if interview.status == "submitted":
        interview.status = "in_progress"
        interview.submitted_at = None
    session.commit()
    return {"id": str(question.id), "answer": question.answer, "answered_at": question.answered_at}


@router.post("/api/v1/candidate/attempts/{attempt_id}/follow-up/submit")
def submit_interview(attempt_id: UUID, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db_session)):
    require_candidate(identity)
    _, interview = _candidate_interview(session, attempt_id, identity, lock=True)
    if interview.status in {"submitted", "reviewed"}:
        return _interview_data(session, interview, private=False)
    questions = session.scalars(select(FollowUpQuestion).where(FollowUpQuestion.interview_id == interview.id).with_for_update()).all()
    if not questions or any(not q.answer.strip() for q in questions):
        raise HTTPException(status_code=422, detail="Answer every follow-up question before submitting")
    for question in questions:
        question.answer_locked = True
    interview.status = "submitted"
    interview.submitted_at = datetime.now(UTC)
    session.commit()
    return _interview_data(session, interview, private=False)


@router.get("/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt_id}/follow-up")
def evaluator_get_interview(assessment_id: UUID, attempt_id: UUID, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db_session)):
    assessment = get_owned_assessment(session, assessment_id, identity)
    interview = session.scalar(select(FollowUpInterview).where(FollowUpInterview.assessment_id == assessment.id, FollowUpInterview.attempt_id == attempt_id))
    if interview is None:
        raise HTTPException(status_code=404, detail="Follow-up interview not found")
    return _interview_data(session, interview, private=True)


@router.post("/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt_id}/follow-up/questions")
def evaluator_add_question(assessment_id: UUID, attempt_id: UUID, data: EvaluatorQuestionInput, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db_session)):
    assessment = get_owned_assessment(session, assessment_id, identity)
    attempt = session.scalar(select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id, AssessmentAttempt.assessment_id == assessment.id).with_for_update())
    if attempt is None or attempt.status != "submitted":
        raise HTTPException(status_code=404, detail="Submitted attempt not found")
    try:
        question_limiter.check(identity.profile.id)
    except RateLimitExceeded as error:
        raise HTTPException(status_code=429, detail="Additional-question limit reached; try again later", headers={"Retry-After": str(error.retry_after_seconds)}) from None
    interview = session.scalar(select(FollowUpInterview).where(FollowUpInterview.attempt_id == attempt.id).with_for_update())
    if interview is None:
        interview = FollowUpInterview(attempt_id=attempt.id, assessment_id=assessment.id, candidate_id=attempt.candidate_id, status="pending")
        session.add(interview)
        session.flush()
    question_count = len(session.scalars(select(FollowUpQuestion.id).where(FollowUpQuestion.interview_id == interview.id)).all())
    if question_count >= MAX_TOTAL_QUESTIONS:
        session.rollback()
        raise HTTPException(status_code=409, detail="This interview has reached its question limit")
    item = FollowUpQuestion(interview_id=interview.id, prompt=data.prompt.strip(), origin="evaluator", created_by=identity.profile.id)
    session.add(item)
    interview.status = "in_progress"
    interview.submitted_at = None
    session.commit()
    return _interview_data(session, interview, private=True)


@router.patch("/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt_id}/follow-up/review")
def evaluator_review_interview(assessment_id: UUID, attempt_id: UUID, data: ReviewInput, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db_session)):
    assessment = get_owned_assessment(session, assessment_id, identity)
    interview = session.scalar(select(FollowUpInterview).where(FollowUpInterview.assessment_id == assessment.id, FollowUpInterview.attempt_id == attempt_id).with_for_update())
    if interview is None:
        raise HTTPException(status_code=404, detail="Follow-up interview not found")
    if interview.status not in {"submitted", "reviewed"}:
        raise HTTPException(status_code=409, detail="Only submitted interviews can be reviewed")
    interview.review_notes = data.notes.strip() or None
    interview.review_score = data.score
    interview.reviewer_id = identity.profile.id
    interview.reviewed_at = datetime.now(UTC)
    interview.status = "reviewed"
    session.commit()
    return _interview_data(session, interview, private=True)
