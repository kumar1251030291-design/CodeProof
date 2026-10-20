"""Candidate-safe assessment discovery and persisted attempt lifecycle."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.authorization import require_candidate
from app.core.config import settings
from app.core.database import get_db_session
from app.core import execution
from app.core.pdf_reports import candidate_attempt_pdf, safe_report_filename
from app.core.result_policy import candidate_result_is_visible
from app.models import (
    AccessCodeRateLimit,
    Assessment,
    AssessmentAccessGrant,
    AssessmentAttempt,
    AttemptResponse,
    Question,
    UserProfile,
)
from app.schemas.candidate_assessment import (
    AccessCodeInput,
    AssessmentAttemptList,
    AssessmentAttemptView,
    AttemptResponseView,
    CandidateAssessmentDetail,
    CandidateAssessmentList,
    CandidateAssessmentSummary,
    CandidateQuestion,
    CandidateResponseInput,
    PublicExample,
    RestrictedAccessResponse,
)

router = APIRouter(prefix="/api/v1/candidate", tags=["candidate assessments"])
RATE_WINDOW = timedelta(minutes=15)
RATE_BLOCK = timedelta(minutes=15)
RATE_LIMIT = 5
GRANT_LIFETIME = timedelta(hours=24)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _available(assessment: Assessment, now: datetime) -> bool:
    if assessment.status != "published":
        return False
    if assessment.starts_at and _utc(assessment.starts_at) > now:
        return False
    if assessment.ends_at and _utc(assessment.ends_at) <= now:
        return False
    return True


def _candidate_summary(assessment: Assessment) -> CandidateAssessmentSummary:
    return CandidateAssessmentSummary(
        id=assessment.id,
        title=assessment.title,
        description=assessment.description,
        instructions=assessment.instructions,
        difficulty=assessment.difficulty,
        duration_seconds=assessment.duration_seconds,
        allowed_languages=assessment.allowed_languages,
        question_count=len(assessment.questions),
        starts_at=assessment.starts_at,
        ends_at=assessment.ends_at,
        max_attempts=assessment.max_attempts,
    )


def _candidate_detail(assessment: Assessment) -> CandidateAssessmentDetail:
    summary = _candidate_summary(assessment)
    questions = [
        CandidateQuestion(
            id=question.id,
            title=question.title,
            prompt=question.prompt,
            question_type=question.question_type,
            difficulty=question.difficulty,
            points=question.points,
            default_language=question.default_language,
            allowed_languages=question.allowed_languages,
            time_limit_seconds=question.time_limit_seconds,
            display_order=question.display_order,
            problem_statement=question.problem_statement,
            examples=question.examples,
            answer_options=question.answer_options,
            public_examples=[
                PublicExample(
                    input_data=case.input_data,
                    expected_output=case.expected_output,
                    display_order=case.display_order,
                )
                for case in question.test_cases
                if case.visibility == "public"
            ],
        )
        for question in assessment.questions
    ]
    return CandidateAssessmentDetail(**summary.model_dump(), questions=questions)


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="The requested assessment action conflicts with current data") from None
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=503, detail="Assessment storage is unavailable") from None


def _lock_candidate(session: Session, identity: AuthenticatedIdentity) -> None:
    profile = session.scalar(
        select(UserProfile).where(UserProfile.id == identity.profile.id).with_for_update()
    )
    if profile is None:
        raise HTTPException(status_code=401, detail="Authenticated profile is unavailable")


def _record_code_failure(session: Session, candidate_id: UUID, now: datetime) -> None:
    limiter = session.get(AccessCodeRateLimit, candidate_id)
    if limiter is None:
        limiter = AccessCodeRateLimit(
            candidate_id=candidate_id,
            window_started_at=now,
            failed_attempts=1,
        )
        session.add(limiter)
    elif now - _utc(limiter.window_started_at) >= RATE_WINDOW:
        limiter.window_started_at = now
        limiter.failed_attempts = 1
        limiter.blocked_until = None
    else:
        limiter.failed_attempts += 1
        if limiter.failed_attempts >= RATE_LIMIT:
            limiter.blocked_until = now + RATE_BLOCK


def _grant_for_candidate(session: Session, assessment: Assessment, candidate_id: UUID, now: datetime) -> AssessmentAccessGrant | None:
    grant = session.get(AssessmentAccessGrant, (candidate_id, assessment.id))
    if grant is None or _utc(grant.expires_at) <= now:
        return None
    return grant


def _load_candidate_assessment(session: Session, assessment_id: UUID) -> Assessment | None:
    return session.scalar(
        select(Assessment)
        .where(Assessment.id == assessment_id)
        .options(selectinload(Assessment.questions).selectinload(Question.test_cases))
    )


def _attempt_count(session: Session, candidate_id: UUID, assessment_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count(AssessmentAttempt.id)).where(
                AssessmentAttempt.candidate_id == candidate_id,
                AssessmentAttempt.assessment_id == assessment_id,
            )
        )
        or 0
    )


def _has_attempt_capacity(session: Session, candidate_id: UUID, assessment: Assessment, now: datetime) -> bool:
    if assessment.max_attempts is None:
        return True
    in_progress = session.scalar(
        select(AssessmentAttempt.id).where(
            AssessmentAttempt.candidate_id == candidate_id,
            AssessmentAttempt.assessment_id == assessment.id,
            AssessmentAttempt.status == "in_progress",
            AssessmentAttempt.deadline_at > now,
        )
    )
    return in_progress is not None or _attempt_count(session, candidate_id, assessment.id) < assessment.max_attempts


def _require_access(session: Session, assessment: Assessment, identity: AuthenticatedIdentity, now: datetime) -> None:
    if assessment.access_mode == "public":
        if not _available(assessment, now):
            raise HTTPException(status_code=404, detail="Assessment not found or unavailable")
        return
    if assessment.access_mode != "restricted" or not _available(assessment, now):
        raise HTTPException(status_code=404, detail="Assessment not found or unavailable")
    grant = _grant_for_candidate(session, assessment, identity.profile.id, now)
    active_attempt = session.scalar(
        select(AssessmentAttempt.id).where(
            AssessmentAttempt.assessment_id == assessment.id,
            AssessmentAttempt.candidate_id == identity.profile.id,
            AssessmentAttempt.status == "in_progress",
            AssessmentAttempt.deadline_at > now,
        )
    )
    if grant is None and active_attempt is None:
        raise HTTPException(status_code=404, detail="Assessment not found or unavailable")


def _attempt_view(session: Session, attempt: AssessmentAttempt, assessment_title: str) -> AssessmentAttemptView:
    responses = session.scalars(
        select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id).order_by(AttemptResponse.saved_at)
    ).all()
    assessment = session.get(Assessment, attempt.assessment_id)
    reveal_score = candidate_result_is_visible(assessment, attempt)
    return AssessmentAttemptView(
        id=attempt.id,
        assessment_id=attempt.assessment_id,
        assessment_title=assessment_title,
        attempt_number=attempt.attempt_number,
        started_at=attempt.started_at,
        deadline_at=attempt.deadline_at,
        status=attempt.status,
        submitted_at=attempt.submitted_at,
        execution_status=attempt.execution_status,
        score=attempt.final_score if reveal_score else None,
        max_score=attempt.max_score if reveal_score else None,
        responses=[
            AttemptResponseView(
                question_id=response.question_id,
                response_text=response.response_text,
                programming_language=response.programming_language,
                saved_at=response.saved_at,
                execution_status=response.execution_status,
                score=response.score if reveal_score else None,
            )
            for response in responses
        ],
    )


@router.get("/assessments", response_model=CandidateAssessmentList)
def discover_open_assessments(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> CandidateAssessmentList:
    require_candidate(identity)
    now = datetime.now(UTC)
    count = (
        select(func.count(AssessmentAttempt.id))
        .where(
            AssessmentAttempt.assessment_id == Assessment.id,
            AssessmentAttempt.candidate_id == identity.profile.id,
        )
        .correlate(Assessment)
        .scalar_subquery()
    )
    assessments = session.scalars(
        select(Assessment)
        .where(
            Assessment.access_mode == "public",
            Assessment.status == "published",
            or_(Assessment.starts_at.is_(None), Assessment.starts_at <= now),
            or_(Assessment.ends_at.is_(None), Assessment.ends_at > now),
            or_(Assessment.max_attempts.is_(None), count < Assessment.max_attempts),
        )
        .options(selectinload(Assessment.questions))
        .order_by(Assessment.published_at.desc())
    ).all()
    return CandidateAssessmentList(assessments=[_candidate_summary(item) for item in assessments])


@router.post("/assessments/access-code", response_model=RestrictedAccessResponse)
def verify_restricted_access_code(
    data: AccessCodeInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> RestrictedAccessResponse:
    require_candidate(identity)
    now = datetime.now(UTC)
    _lock_candidate(session, identity)
    limiter = session.get(AccessCodeRateLimit, identity.profile.id)
    if limiter and limiter.blocked_until and _utc(limiter.blocked_until) > now:
        session.rollback()
        raise HTTPException(status_code=429, detail="Too many code checks. Try again later")

    digest = hashlib.sha256(data.access_code.strip().encode("utf-8")).hexdigest()
    assessment = session.scalar(
        select(Assessment)
        .where(Assessment.access_code_hash == digest)
        .options(selectinload(Assessment.questions).selectinload(Question.test_cases))
    )
    valid = (
        assessment is not None
        and hmac.compare_digest(assessment.access_code_hash or "", digest)
        and assessment.access_mode == "restricted"
        and _available(assessment, now)
        and _has_attempt_capacity(session, identity.profile.id, assessment, now)
    )
    if not valid or assessment is None:
        _record_code_failure(session, identity.profile.id, now)
        _commit(session)
        raise HTTPException(status_code=404, detail="Access code invalid or assessment unavailable")

    grant_expiry = now + GRANT_LIFETIME
    if assessment.ends_at and _utc(assessment.ends_at) < grant_expiry:
        grant_expiry = _utc(assessment.ends_at)
    grant = session.get(AssessmentAccessGrant, (identity.profile.id, assessment.id))
    if grant is None:
        session.add(
            AssessmentAccessGrant(
                candidate_id=identity.profile.id,
                assessment_id=assessment.id,
                granted_at=now,
                expires_at=grant_expiry,
            )
        )
    else:
        grant.granted_at = now
        grant.expires_at = grant_expiry
    if limiter:
        limiter.failed_attempts = 0
        limiter.blocked_until = None
    _commit(session)
    return RestrictedAccessResponse(
        assessment=_candidate_detail(assessment),
        grant_expires_at=grant_expiry,
    )


@router.get("/assessments/{assessment_id}", response_model=CandidateAssessmentDetail)
def get_candidate_assessment(
    assessment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> CandidateAssessmentDetail:
    require_candidate(identity)
    assessment = _load_candidate_assessment(session, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found or unavailable")
    now = datetime.now(UTC)
    _require_access(session, assessment, identity, now)
    if not _has_attempt_capacity(session, identity.profile.id, assessment, now):
        raise HTTPException(status_code=404, detail="Assessment not found or unavailable")
    return _candidate_detail(assessment)


@router.post("/assessments/{assessment_id}/attempts", response_model=AssessmentAttemptView)
def start_or_resume_attempt(
    assessment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentAttemptView:
    require_candidate(identity)
    _lock_candidate(session, identity)  # Serializes starts for this candidate, protecting max-attempt checks.
    now = datetime.now(UTC)
    assessment = session.scalar(
        select(Assessment)
        .where(Assessment.id == assessment_id)
        .with_for_update()
        .options(selectinload(Assessment.questions))
    )
    if assessment is None:
        session.rollback()
        raise HTTPException(status_code=404, detail="Assessment not found or unavailable")
    _require_access(session, assessment, identity, now)

    current = session.scalar(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.assessment_id == assessment.id,
            AssessmentAttempt.candidate_id == identity.profile.id,
            AssessmentAttempt.status == "in_progress",
        )
        .order_by(AssessmentAttempt.started_at.desc())
        .with_for_update()
    )
    if current and _utc(current.deadline_at) > now:
        result = _attempt_view(session, current, assessment.title)
        session.commit()
        return result
    if current:
        current.status = "expired"
        session.flush()

    count = _attempt_count(session, identity.profile.id, assessment.id)
    if assessment.max_attempts is not None and count >= assessment.max_attempts:
        session.rollback()
        raise HTTPException(status_code=409, detail="No attempts remain for this assessment")

    deadline = now + timedelta(seconds=assessment.duration_seconds)
    if assessment.ends_at and _utc(assessment.ends_at) < deadline:
        deadline = _utc(assessment.ends_at)
    attempt = AssessmentAttempt(
        candidate_id=identity.profile.id,
        assessment_id=assessment.id,
        attempt_number=count + 1,
        started_at=now,
        deadline_at=deadline,
        status="in_progress",
    )
    session.add(attempt)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Could not start an attempt; retry the request") from None
    result = _attempt_view(session, attempt, assessment.title)
    _commit(session)
    return result


@router.get("/attempts", response_model=AssessmentAttemptList)
def list_candidate_attempts(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentAttemptList:
    require_candidate(identity)
    now = datetime.now(UTC)
    attempts = session.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.candidate_id == identity.profile.id)
        .order_by(AssessmentAttempt.started_at.desc())
    ).all()
    expired_changed = False
    output = []
    for attempt in attempts:
        if attempt.status == "in_progress" and _utc(attempt.deadline_at) <= now:
            attempt.status = "expired"
            expired_changed = True
        title = session.scalar(select(Assessment.title).where(Assessment.id == attempt.assessment_id)) or "Assessment"
        output.append(_attempt_view(session, attempt, title))
    if expired_changed:
        _commit(session)
    return AssessmentAttemptList(attempts=output)


def _owned_attempt(session: Session, attempt_id: UUID, identity: AuthenticatedIdentity) -> AssessmentAttempt:
    attempt = session.scalar(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.id == attempt_id,
            AssessmentAttempt.candidate_id == identity.profile.id,
        )
        .with_for_update()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt


@router.get("/attempts/{attempt_id}", response_model=AssessmentAttemptView)
def get_candidate_attempt(
    attempt_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentAttemptView:
    require_candidate(identity)
    attempt = _owned_attempt(session, attempt_id, identity)
    if attempt.status == "in_progress" and _utc(attempt.deadline_at) <= datetime.now(UTC):
        attempt.status = "expired"
        _commit(session)
    title = session.scalar(select(Assessment.title).where(Assessment.id == attempt.assessment_id)) or "Assessment"
    return _attempt_view(session, attempt, title)


@router.get("/attempts/{attempt_id}/report.pdf", response_class=Response, tags=["candidate reports"])
def download_candidate_attempt_report(
    attempt_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> Response:
    """Create a private PDF for the authenticated candidate's own attempt."""
    require_candidate(identity)
    attempt = _owned_attempt(session, attempt_id, identity)
    if attempt.status == "in_progress" and _utc(attempt.deadline_at) <= datetime.now(UTC):
        attempt.status = "expired"
        _commit(session)
    assessment = session.get(Assessment, attempt.assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    responses = session.scalars(
        select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)
    ).all()
    try:
        content = candidate_attempt_pdf(
            assessment, attempt, identity.profile, identity.email, responses,
            results_visible=candidate_result_is_visible(assessment, attempt),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Candidate report could not be generated") from None
    filename = safe_report_filename("candidate-attempt", attempt.id)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


def _require_active_attempt(session: Session, attempt_id: UUID, identity: AuthenticatedIdentity) -> AssessmentAttempt:
    attempt = _owned_attempt(session, attempt_id, identity)
    if attempt.status != "in_progress":
        raise HTTPException(status_code=409, detail="This attempt is no longer accepting responses")
    if _utc(attempt.deadline_at) <= datetime.now(UTC):
        attempt.status = "expired"
        _commit(session)
        raise HTTPException(status_code=409, detail="The attempt deadline has passed")
    return attempt


@router.put("/attempts/{attempt_id}/responses/{question_id}", response_model=AttemptResponseView)
def save_candidate_response(
    attempt_id: UUID,
    question_id: UUID,
    data: CandidateResponseInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AttemptResponseView:
    require_candidate(identity)
    attempt = _require_active_attempt(session, attempt_id, identity)
    question = session.scalar(
        select(Question).where(
            Question.id == question_id,
            Question.assessment_id == attempt.assessment_id,
        )
    )
    if question is None:
        session.rollback()
        raise HTTPException(status_code=404, detail="Question not found")
    if question.question_type in {"programming", "debugging"}:
        if data.programming_language not in (question.allowed_languages or [question.default_language]):
            raise HTTPException(status_code=422, detail="Choose a language allowed for this question")
    elif data.programming_language is not None:
        raise HTTPException(status_code=422, detail="A programming language is not used for this question")
    response = session.scalar(
        select(AttemptResponse)
        .where(AttemptResponse.attempt_id == attempt.id, AttemptResponse.question_id == question.id)
        .with_for_update()
    )
    if response is None:
        response = AttemptResponse(attempt_id=attempt.id, question_id=question.id, response_text=data.response_text)
        session.add(response)
    response.response_text = data.response_text
    response.programming_language = data.programming_language
    _commit(session)
    session.refresh(response)
    return AttemptResponseView(
        question_id=response.question_id,
        response_text=response.response_text,
        programming_language=response.programming_language,
        saved_at=response.saved_at,
    )


@router.post("/attempts/{attempt_id}/submit", response_model=AssessmentAttemptView)
def submit_candidate_attempt(
    attempt_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentAttemptView:
    require_candidate(identity)
    attempt = _require_active_attempt(session, attempt_id, identity)
    assessment = session.scalar(
        select(Assessment).where(Assessment.id == attempt.assessment_id)
        .options(selectinload(Assessment.questions).selectinload(Question.test_cases))
    )
    if assessment is None or assessment.status != "published" or not _available(assessment, datetime.now(UTC)):
        raise HTTPException(status_code=409, detail="The assessment is no longer available for submission")
    attempt.status = "submitted"
    attempt.submitted_at = datetime.now(UTC)
    attempt.execution_status = "running" if settings.code_execution_enabled else "unavailable"
    _commit(session)
    if settings.code_execution_enabled:
        try:
            _score_attempt(session, attempt, assessment)
        except Exception:
            session.rollback()
            attempt = session.get(AssessmentAttempt, attempt_id)
            if attempt is not None:
                attempt.execution_status = "failed"
                for response in session.scalars(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt_id)).all():
                    response.execution_status = "failed"
                session.commit()
        else:
            session.commit()
    else:
        for response in session.scalars(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)).all():
            response.execution_status = "unavailable"
        session.commit()
    title = assessment.title
    return _attempt_view(session, attempt, title)


def _score_attempt(session: Session, attempt: AssessmentAttempt, assessment: Assessment) -> None:
    responses = {
        item.question_id: item
        for item in session.scalars(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)).all()
    }
    total_score = 0
    max_score = sum(question.points for question in assessment.questions)
    manual_review = False
    requires_manual_review = False
    for question in assessment.questions:
        response = responses.get(question.id)
        if response is None and question.question_type == "explanation":
            response = AttemptResponse(
                attempt_id=attempt.id, question_id=question.id, response_text="",
                execution_status="manual_review",
            )
            session.add(response)
            responses[question.id] = response
        if response is None:
            continue
        if question.question_type not in {"programming", "debugging"}:
            if question.question_type in {"multiple_choice", "multiple-choice"} and question.correct_answer is not None:
                passed = response.response_text.strip() == question.correct_answer.strip()
                response.execution_status = "completed"
                response.score = question.points if passed else 0
                response.passed_test_cases = int(passed)
                response.total_test_cases = 1
                total_score += response.score
            else:
                response.execution_status = "manual_review"
                manual_review = True
                requires_manual_review = True
            continue
        if not response.response_text:
            response.execution_status = "completed"
            response.score = 0
            response.passed_test_cases = 0
            response.total_test_cases = len(question.test_cases)
            continue
        language = response.programming_language
        question_languages = question.allowed_languages or [question.default_language]
        if language not in (assessment.allowed_languages or []) or language not in question_languages:
            response.execution_status = "failed"
            response.execution_details = []
            manual_review = True
            continue
        ordered_cases = sorted(question.test_cases, key=lambda case: case.display_order)
        try:
            details, passed_count = execution.run_question(
                language,
                response.response_text,
                [(case.input_data, case.expected_output) for case in ordered_cases],
            )
        except execution.RunnerUnavailable:
            for pending in responses.values():
                if pending.execution_status == "not_started":
                    pending.execution_status = "unavailable"
                    pending.execution_details = []
            attempt.execution_status = "unavailable"
            session.flush()
            return
        except ValueError:
            response.execution_status = "failed"
            response.execution_details = []
            manual_review = True
            continue
        response.execution_details = details
        response.passed_test_cases = passed_count
        response.total_test_cases = len(ordered_cases)
        response.score = (question.points * passed_count) // len(ordered_cases) if ordered_cases else 0
        total_score += response.score
        failures = [str(item["status"]) for item in details if item["status"] != "completed"]
        response.execution_status = failures[0] if failures else "completed"
    attempt.score = total_score
    attempt.max_score = max_score
    attempt.execution_status = "manual_review" if manual_review else "completed"
    attempt.manual_score = None
    attempt.review_status = "pending" if requires_manual_review else "not_required"
    attempt.final_score = None if requires_manual_review else total_score
