"""Owner-scoped evaluator assessment and question management endpoints."""

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.authorization import (
    assign_verified_owner,
    get_owned_assessment,
    list_owned_assessments,
    require_evaluator,
)
from app.core.database import get_db_session
from app.core import execution
from app.core.config import settings
from app.core.pdf_reports import evaluator_attempt_pdf, safe_report_filename
from app.models import Assessment, AssessmentAccessGrant, AssessmentAttempt, AttemptResponse, Question, TestCase, UserProfile
from app.schemas.assessment import (
    AccessCodeResponse,
    AssessmentDetail,
    AssessmentDraftInput,
    AssessmentListResponse,
    AssessmentSummary,
    AssessmentUpdateInput,
    QuestionInput,
    QuestionOrderInput,
    QuestionResponse,
    TestCaseResponse,
    AssessmentResultsResponse,
    EvaluationAttemptResult,
    EvaluationQuestionResult,
    ManualReviewInput,
)

router = APIRouter(prefix="/api/v1/evaluator/assessments", tags=["evaluator assessments"])


@router.get("/{assessment_id}/results", response_model=AssessmentResultsResponse)
def get_assessment_results(
    assessment_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentResultsResponse:
    """Return private candidate submissions only to the verified assessment owner."""
    assessment = get_owned_assessment(session, assessment_id, identity)
    total = session.scalar(
        select(func.count(AssessmentAttempt.id)).where(AssessmentAttempt.assessment_id == assessment.id)
    ) or 0
    attempts = session.scalars(
        select(AssessmentAttempt).where(AssessmentAttempt.assessment_id == assessment.id)
        .order_by(AssessmentAttempt.started_at.desc()).limit(limit).offset(offset)
    ).all()
    attempt_results = []
    for attempt in attempts:
        records = session.scalars(
            select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)
        ).all()
        record_by_question = {record.question_id: record for record in records}
        responses = []
        for question in assessment.questions:
            record = record_by_question.get(question.id)
            responses.append(EvaluationQuestionResult(
                question_id=question.id,
                question_title=question.title,
                question_type=question.question_type,
                question_prompt=question.prompt,
                max_points=question.points,
                response_text=record.response_text if record else None,
                programming_language=record.programming_language if record else None,
                execution_status=record.execution_status if record else "not_started",
                score=record.score if record else None,
                passed_test_cases=record.passed_test_cases if record else None,
                total_test_cases=record.total_test_cases if record else None,
                execution_details=record.execution_details if record else None,
                manual_score=record.manual_score if record else None,
                manual_feedback=record.manual_feedback if record else None,
                reviewed_at=record.reviewed_at if record else None,
                review_eligible=question.question_type == "explanation" and attempt.status == "submitted",
            ))
        profile = session.get(UserProfile, attempt.candidate_id)
        attempt_results.append(EvaluationAttemptResult(
            attempt_id=attempt.id,
            candidate_id=attempt.candidate_id,
            candidate_display_name=profile.display_name if profile else None,
            attempt_number=attempt.attempt_number,
            status=attempt.status,
            execution_status=attempt.execution_status,
            started_at=attempt.started_at,
            submitted_at=attempt.submitted_at,
            score=attempt.score,
            max_score=attempt.max_score,
            manual_score=attempt.manual_score,
            final_score=attempt.final_score,
            review_status=attempt.review_status,
            responses=responses,
        ))
    return AssessmentResultsResponse(assessment_id=assessment.id, attempts=attempt_results, total=total, limit=limit, offset=offset)


@router.get("/{assessment_id}/attempts/{attempt_id}/report.pdf", response_class=Response, tags=["evaluator reports"])
def download_evaluator_attempt_report(
    assessment_id: UUID,
    attempt_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> Response:
    """Export a detailed submission only when both owner and attempt scope match."""
    assessment = get_owned_assessment(session, assessment_id, identity)
    attempt = session.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.id == attempt_id,
            AssessmentAttempt.assessment_id == assessment.id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Assessment attempt not found")
    responses = session.scalars(
        select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)
    ).all()
    candidate = session.get(UserProfile, attempt.candidate_id)
    try:
        content = evaluator_attempt_pdf(assessment, attempt, candidate, responses)
    except Exception:
        raise HTTPException(status_code=500, detail="Evaluator report could not be generated") from None
    filename = safe_report_filename("evaluator-submission", attempt.id)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


@router.patch("/{assessment_id}/attempts/{attempt_id}/questions/{question_id}/review", response_model=EvaluationAttemptResult)
def save_question_review(
    assessment_id: UUID,
    attempt_id: UUID,
    question_id: UUID,
    data: ManualReviewInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> EvaluationAttemptResult:
    """Save an owner-authorized written-answer grade and recompute totals on the server."""
    assessment = get_owned_assessment(session, assessment_id, identity)
    attempt = session.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.id == attempt_id,
            AssessmentAttempt.assessment_id == assessment.id,
        ).with_for_update()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Assessment attempt not found")
    if attempt.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted attempts can be reviewed")
    question = session.scalar(select(Question).where(Question.id == question_id, Question.assessment_id == assessment.id))
    if question is None:
        raise HTTPException(status_code=404, detail="Assessment question not found")
    if question.question_type != "explanation":
        raise HTTPException(status_code=409, detail="This question is not eligible for manual grading")
    if data.score > question.points:
        raise HTTPException(status_code=422, detail="Score cannot exceed the question's maximum points")

    response = session.scalar(select(AttemptResponse).where(
        AttemptResponse.attempt_id == attempt.id,
        AttemptResponse.question_id == question.id,
    ))
    if response is None:
        response = AttemptResponse(attempt_id=attempt.id, question_id=question.id, response_text="", execution_status="manual_review")
        session.add(response)
    response.manual_score = data.score
    response.manual_feedback = data.feedback.strip() if data.feedback and data.feedback.strip() else None
    response.reviewer_id = identity.profile.id
    response.reviewed_at = datetime.now(UTC)
    session.flush()

    written_questions = [item for item in assessment.questions if item.question_type == "explanation"]
    written_responses = session.scalars(select(AttemptResponse).where(
        AttemptResponse.attempt_id == attempt.id,
        AttemptResponse.question_id.in_([item.id for item in written_questions]),
    )).all() if written_questions else []
    grades = {item.question_id: item.manual_score for item in written_responses}
    attempt.manual_score = sum(score for score in grades.values() if score is not None)
    all_reviewed = bool(written_questions) and all(grades.get(item.id) is not None for item in written_questions)
    if all_reviewed:
        attempt.review_status = "complete"
        if attempt.score is not None:
            attempt.final_score = attempt.score + (attempt.manual_score or 0)
            attempt.execution_status = "completed"
        else:
            # Manual grading can finish even when automatic execution was unavailable;
            # never present a manual-only subtotal as the final assessment score.
            attempt.final_score = None
    else:
        attempt.review_status = "pending"
        attempt.final_score = None
        attempt.execution_status = "manual_review"
    session.commit()
    return _evaluation_attempt_result(session, assessment, attempt)


def _evaluation_attempt_result(session: Session, assessment: Assessment, attempt: AssessmentAttempt) -> EvaluationAttemptResult:
    """Build the same private, assessment-scoped detail returned by the results list."""
    records = session.scalars(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id)).all()
    by_question = {item.question_id: item for item in records}
    responses = []
    for question in assessment.questions:
        record = by_question.get(question.id)
        responses.append(EvaluationQuestionResult(
            question_id=question.id, question_title=question.title, question_type=question.question_type,
            question_prompt=question.prompt, max_points=question.points,
            response_text=record.response_text if record else None,
            programming_language=record.programming_language if record else None,
            execution_status=record.execution_status if record else "not_started",
            score=record.score if record else None, passed_test_cases=record.passed_test_cases if record else None,
            total_test_cases=record.total_test_cases if record else None,
            execution_details=record.execution_details if record else None,
            manual_score=record.manual_score if record else None,
            manual_feedback=record.manual_feedback if record else None,
            reviewed_at=record.reviewed_at if record else None,
            review_eligible=question.question_type == "explanation" and attempt.status == "submitted",
        ))
    profile = session.get(UserProfile, attempt.candidate_id)
    return EvaluationAttemptResult(
        attempt_id=attempt.id, candidate_id=attempt.candidate_id,
        candidate_display_name=profile.display_name if profile else None,
        attempt_number=attempt.attempt_number, status=attempt.status,
        execution_status=attempt.execution_status, started_at=attempt.started_at,
        submitted_at=attempt.submitted_at, score=attempt.score, max_score=attempt.max_score,
        manual_score=attempt.manual_score, final_score=attempt.final_score,
        review_status=attempt.review_status, responses=responses,
    )


def _generate_access_code(session: Session) -> tuple[str, str]:
    """Generate a high-entropy one-time code and its SHA-256 lookup hash."""
    for _ in range(5):
        code = secrets.token_urlsafe(24)
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        existing = session.scalar(
            select(Assessment.id).where(Assessment.access_code_hash == digest)
        )
        if existing is None:
            return code, digest
    raise HTTPException(status_code=503, detail="Could not generate a unique access code")


def _access_mode_to_storage(access_mode: str) -> str:
    return "public" if access_mode == "open" else "restricted"


def _access_mode_from_storage(access_mode: str) -> str:
    return "open" if access_mode == "public" else "restricted"


def _to_summary(assessment: Assessment) -> AssessmentSummary:
    return AssessmentSummary(
        id=assessment.id,
        title=assessment.title,
        description=assessment.description,
        instructions=assessment.instructions,
        status=assessment.status,
        difficulty=assessment.difficulty,
        duration_seconds=assessment.duration_seconds,
        allowed_languages=assessment.allowed_languages,
        access_mode=_access_mode_from_storage(assessment.access_mode),
        purpose=assessment.purpose,
        max_attempts=assessment.max_attempts,
        starts_at=assessment.starts_at,
        ends_at=assessment.ends_at,
        published_at=assessment.published_at,
        show_results_after_submission=assessment.show_results_after_submission,
        question_count=len(assessment.questions),
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
    )


def _to_detail(assessment: Assessment, access_code: str | None = None) -> AssessmentDetail:
    summary = _to_summary(assessment)
    questions = [
        QuestionResponse(
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
            correct_answer=question.correct_answer,
            test_cases=[
                TestCaseResponse(
                    id=test_case.id,
                    input_data=test_case.input_data,
                    expected_output=test_case.expected_output,
                    visibility=test_case.visibility,
                    display_order=test_case.display_order,
                )
                for test_case in question.test_cases
            ],
        )
        for question in assessment.questions
    ]
    return AssessmentDetail(**summary.model_dump(), questions=questions, access_code=access_code)


def _ensure_draft(assessment: Assessment) -> None:
    if assessment.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft assessments can be edited")


def _validate_question_languages(question_input: QuestionInput, assessment: Assessment) -> tuple[str, list[str]]:
    assessment_languages = assessment.allowed_languages
    question_languages = question_input.allowed_languages or assessment_languages
    if not set(question_languages).issubset(set(assessment_languages)):
        raise HTTPException(
            status_code=422,
            detail="Question languages must be included in the assessment's allowed languages",
        )
    default_language = question_input.default_language or question_languages[0]
    if default_language not in question_languages:
        raise HTTPException(status_code=422, detail="Default language must be allowed for the question")
    return default_language, question_languages


def _apply_question_fields(
    session: Session,
    question: Question,
    question_input: QuestionInput,
    assessment: Assessment,
    *,
    display_order: int,
) -> None:
    default_language, languages = _validate_question_languages(question_input, assessment)
    question.title = question_input.title
    question.prompt = question_input.prompt
    question.question_type = question_input.question_type
    question.difficulty = question_input.difficulty
    question.points = question_input.points
    question.default_language = default_language
    question.allowed_languages = languages
    question.time_limit_seconds = question_input.time_limit_seconds or assessment.duration_seconds
    question.display_order = display_order
    question.problem_statement = question_input.problem_statement
    question.examples = question_input.examples
    question.answer_options = question_input.answer_options
    question.correct_answer = question_input.correct_answer
    question.test_cases.clear()
    session.flush()
    for order, case_input in enumerate(question_input.test_cases):
        question.test_cases.append(
            TestCase(
                input_data=case_input.input_data,
                expected_output=case_input.expected_output,
                visibility=case_input.visibility,
                display_order=order,
            )
        )


def _apply_assessment_settings(assessment: Assessment, data: AssessmentDraftInput | AssessmentUpdateInput) -> None:
    assessment.title = data.title.strip()
    assessment.description = data.description
    assessment.instructions = data.instructions
    assessment.difficulty = data.difficulty
    assessment.duration_seconds = data.duration_seconds
    assessment.allowed_languages = list(data.allowed_languages)
    assessment.access_mode = _access_mode_to_storage(data.access_mode)
    assessment.purpose = data.purpose
    assessment.max_attempts = data.max_attempts
    assessment.starts_at = data.starts_at
    assessment.ends_at = data.ends_at
    assessment.show_results_after_submission = data.show_results_after_submission


def _replace_questions(
    session: Session,
    assessment: Assessment,
    question_inputs: list[QuestionInput],
) -> None:
    current = {question.id: question for question in assessment.questions}
    requested_ids = [item.id for item in question_inputs if item.id is not None]
    if any(question_id not in current for question_id in requested_ids):
        raise HTTPException(status_code=404, detail="Question not found in this assessment")

    retained_ids = set(requested_ids)
    for question in current.values():
        question.display_order += len(current) + len(question_inputs) + 1
    session.flush()
    assessment.questions[:] = [question for question in assessment.questions if question.id in retained_ids]
    session.flush()

    by_id = {question.id: question for question in assessment.questions}
    ordered_questions: list[Question] = []
    for order, item in enumerate(question_inputs):
        question = by_id.get(item.id) if item.id else None
        if question is None:
            question = Question(
                assessment_id=assessment.id,
                title=item.title,
                prompt=item.prompt,
                question_type=item.question_type,
                default_language=item.default_language or assessment.allowed_languages[0],
                time_limit_seconds=item.time_limit_seconds or assessment.duration_seconds,
                display_order=order,
            )
            assessment.questions.append(question)
        _apply_question_fields(session, question, item, assessment, display_order=order)
        ordered_questions.append(question)
    assessment.questions[:] = ordered_questions


def _commit_or_reject(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=422, detail="Assessment data violates a database constraint") from None
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=503, detail="Assessment storage is unavailable") from None


def _owned_draft(
    session: Session,
    assessment_id: UUID,
    identity: AuthenticatedIdentity,
) -> Assessment:
    assessment = get_owned_assessment(session, assessment_id, identity)
    _ensure_draft(assessment)
    return assessment


@router.post("", response_model=AssessmentDetail, status_code=status.HTTP_201_CREATED)
def create_assessment(
    data: AssessmentDraftInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentDetail:
    require_evaluator(identity)
    assessment = assign_verified_owner(
        Assessment(
            title=data.title,
            description=data.description,
            instructions=data.instructions,
            status="draft",
            difficulty=data.difficulty,
            duration_seconds=data.duration_seconds,
            allowed_languages=list(data.allowed_languages),
            access_mode=_access_mode_to_storage(data.access_mode),
            purpose=data.purpose,
            max_attempts=data.max_attempts,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            show_results_after_submission=data.show_results_after_submission,
        ),
        identity,
    )
    one_time_code: str | None = None
    if data.access_mode == "restricted":
        one_time_code, assessment.access_code_hash = _generate_access_code(session)
    session.add(assessment)
    try:
        session.flush()
        _replace_questions(session, assessment, data.questions)
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=422, detail="Assessment could not be saved") from None
    _commit_or_reject(session)
    return _to_detail(assessment, one_time_code)


@router.get("", response_model=AssessmentListResponse)
def list_assessments(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentListResponse:
    assessments = list_owned_assessments(session, identity)
    return AssessmentListResponse(assessments=[_to_summary(assessment) for assessment in assessments])


@router.get("/{assessment_id}", response_model=AssessmentDetail)
def get_assessment(
    assessment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentDetail:
    return _to_detail(get_owned_assessment(session, assessment_id, identity))


@router.put("/{assessment_id}", response_model=AssessmentDetail)
def update_assessment(
    assessment_id: UUID,
    data: AssessmentUpdateInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentDetail:
    assessment = _owned_draft(session, assessment_id, identity)
    previous_access_mode = assessment.access_mode
    _apply_assessment_settings(assessment, data)
    one_time_code: str | None = None
    if data.access_mode == "restricted" and (
        previous_access_mode != "restricted" or assessment.access_code_hash is None
    ):
        one_time_code, assessment.access_code_hash = _generate_access_code(session)
    elif data.access_mode == "open":
        assessment.access_code_hash = None

    try:
        _replace_questions(session, assessment, data.questions)
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=422, detail="Questions could not be saved") from None
    _commit_or_reject(session)
    return _to_detail(assessment, one_time_code)


@router.delete("/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    assessment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> Response:
    assessment = _owned_draft(session, assessment_id, identity)
    session.delete(assessment)
    _commit_or_reject(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{assessment_id}/archive", response_model=AssessmentDetail)
def archive_assessment(
    assessment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentDetail:
    assessment = get_owned_assessment(session, assessment_id, identity)
    if assessment.status == "archived":
        return _to_detail(assessment)
    assessment.status = "archived"
    _commit_or_reject(session)
    return _to_detail(assessment)


def _validate_for_publication(assessment: Assessment) -> None:
    if not assessment.description.strip() or not assessment.instructions.strip():
        raise HTTPException(status_code=422, detail="Description and candidate instructions are required to publish")
    if not assessment.allowed_languages or not set(assessment.allowed_languages).issubset({"python", "c"}):
        raise HTTPException(status_code=422, detail="Select at least one supported language")
    if not assessment.questions:
        raise HTTPException(status_code=422, detail="Add at least one question before publishing")
    max_test_cases = min(execution.MAX_TEST_CASES, settings.code_runner_max_cases)
    for question in assessment.questions:
        if question.difficulty not in {"easy", "medium", "hard"} or question.points < 0:
            raise HTTPException(status_code=422, detail="Question settings are incomplete")
        if question.question_type in {"programming", "debugging"}:
            if not question.problem_statement.strip():
                raise HTTPException(status_code=422, detail="Coding questions require a problem statement")
            if not question.test_cases or len(question.test_cases) > max_test_cases:
                raise HTTPException(
                    status_code=422,
                    detail=f"Coding questions require between 1 and {max_test_cases} test cases",
                )
        if question.question_type == "multiple-choice":
            options = [option.strip() for option in question.answer_options if option.strip()]
            if len(options) < 2 or question.correct_answer not in options:
                raise HTTPException(status_code=422, detail="Multiple-choice questions need options and a valid answer key")


@router.post("/{assessment_id}/publish", response_model=AssessmentDetail)
def publish_assessment(
    assessment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AssessmentDetail:
    assessment = _owned_draft(session, assessment_id, identity)
    _validate_for_publication(assessment)
    one_time_code: str | None = None
    if assessment.access_mode == "restricted" and not assessment.access_code_hash:
        one_time_code, assessment.access_code_hash = _generate_access_code(session)
    assessment.status = "published"
    assessment.published_at = datetime.now(UTC)
    _commit_or_reject(session)
    return _to_detail(assessment, one_time_code)


@router.post("/{assessment_id}/access-code", response_model=AccessCodeResponse)
def rotate_access_code(
    assessment_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> AccessCodeResponse:
    assessment = get_owned_assessment(session, assessment_id, identity)
    if assessment.access_mode != "restricted":
        raise HTTPException(status_code=409, detail="Only restricted assessments use access codes")
    code, assessment.access_code_hash = _generate_access_code(session)
    session.execute(
        delete(AssessmentAccessGrant).where(AssessmentAccessGrant.assessment_id == assessment.id)
    )
    _commit_or_reject(session)
    return AccessCodeResponse(assessment_id=assessment.id, access_code=code)


@router.post("/{assessment_id}/questions", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def add_question(
    assessment_id: UUID,
    data: QuestionInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> QuestionResponse:
    assessment = _owned_draft(session, assessment_id, identity)
    order = len(assessment.questions)
    if data.display_order not in {0, order} or data.id is not None:
        raise HTTPException(status_code=422, detail="New questions are appended in order")
    question = Question(
        assessment_id=assessment.id,
        title=data.title,
        prompt=data.prompt,
        question_type=data.question_type,
        default_language=data.default_language or assessment.allowed_languages[0],
        time_limit_seconds=data.time_limit_seconds or assessment.duration_seconds,
        display_order=order,
    )
    _apply_question_fields(session, question, data, assessment, display_order=order)
    assessment.questions.append(question)
    _commit_or_reject(session)
    session.refresh(question)
    return _to_question_response(question)


def _to_question_response(question: Question) -> QuestionResponse:
    return QuestionResponse(
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
        correct_answer=question.correct_answer,
        test_cases=[
            TestCaseResponse(
                id=case.id,
                input_data=case.input_data,
                expected_output=case.expected_output,
                visibility=case.visibility,
                display_order=case.display_order,
            )
            for case in question.test_cases
        ],
    )


@router.put("/{assessment_id}/questions/{question_id:uuid}", response_model=QuestionResponse)
def update_question(
    assessment_id: UUID,
    question_id: UUID,
    data: QuestionInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> QuestionResponse:
    assessment = _owned_draft(session, assessment_id, identity)
    question = next((item for item in assessment.questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if data.id not in {None, question_id} or data.display_order != question.display_order:
        raise HTTPException(status_code=422, detail="Use the reorder endpoint to change question order")
    _apply_question_fields(session, question, data, assessment, display_order=question.display_order)
    _commit_or_reject(session)
    session.refresh(question)
    return _to_question_response(question)


@router.delete("/{assessment_id}/questions/{question_id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    assessment_id: UUID,
    question_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> Response:
    assessment = _owned_draft(session, assessment_id, identity)
    question = next((item for item in assessment.questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    assessment.questions.remove(question)
    session.flush()
    _reorder_questions(session, [item for item in assessment.questions])
    _commit_or_reject(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _reorder_questions(session: Session, ordered: list[Question]) -> None:
    offset = len(ordered) + max((question.display_order for question in ordered), default=0) + 1
    for question in ordered:
        question.display_order += offset
    session.flush()
    for index, question in enumerate(ordered):
        question.display_order = index


@router.put("/{assessment_id}/questions/reorder", response_model=list[QuestionResponse])
def reorder_questions(
    assessment_id: UUID,
    data: QuestionOrderInput,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db_session),
) -> list[QuestionResponse]:
    assessment = _owned_draft(session, assessment_id, identity)
    by_id = {question.id: question for question in assessment.questions}
    if len(set(data.question_ids)) != len(data.question_ids) or set(data.question_ids) != set(by_id):
        raise HTTPException(status_code=422, detail="Order must include every question exactly once")
    ordered = [by_id[question_id] for question_id in data.question_ids]
    _reorder_questions(session, ordered)
    _commit_or_reject(session)
    return [_to_question_response(question) for question in ordered]
