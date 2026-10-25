"""Initial assessment content models."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for ORM-side defaults and updates."""
    return datetime.now(UTC)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        CheckConstraint("length(trim(status)) > 0", name="status_not_empty"),
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="difficulty_valid"),
        CheckConstraint("access_mode IN ('restricted', 'public')", name="access_mode_valid"),
        CheckConstraint(
            "purpose IS NULL OR purpose IN ('hiring', 'practice')",
            name="purpose_valid",
        ),
        CheckConstraint("duration_seconds > 0", name="duration_positive"),
        CheckConstraint(
            "max_attempts IS NULL OR max_attempts > 0",
            name="max_attempts_positive",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR starts_at < ends_at",
            name="availability_range_valid",
        ),
        CheckConstraint(
            "access_code_hash IS NULL OR length(trim(access_code_hash)) > 0",
            name="access_code_hash_not_empty",
        ),
        UniqueConstraint("access_code_hash", name="uq_assessments_access_code_hash"),
        Index("ix_assessments_status", "status"),
        Index("ix_assessments_owner_id", "owner_id"),
        Index("ix_assessments_discovery", "access_mode", "status", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "user_profiles.id",
            ondelete="SET NULL",
            name="fk_assessments_owner_id_user_profiles",
        ),
        nullable=True,
    )
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    access_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="restricted", server_default="restricted"
    )
    purpose: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3600, server_default="3600"
    )
    allowed_languages: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["python", "c"],
        server_default=sql_text("'[\"python\", \"c\"]'"),
    )
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    show_results_after_submission: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=sql_text("false")
    )

    questions: Mapped[list["Question"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Question.display_order",
    )
    owner: Mapped["UserProfile | None"] = relationship(
        back_populates="owned_assessments",
        foreign_keys=[owner_id],
    )


class UserProfile(Base):
    """Application profile keyed by the authenticated provider's user UUID."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "display_name IS NULL OR length(trim(display_name)) > 0",
            name="display_name_not_empty",
        ),
    )

    # Supabase Auth owns the UUID; no auth.users foreign key is required locally.
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    owned_assessments: Mapped[list[Assessment]] = relationship(
        back_populates="owner",
        foreign_keys="Assessment.owner_id",
    )


class UserRole(Base):
    """Normalized role assignment; only trusted server code should grant roles."""

    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint("role IN ('evaluator', 'candidate')", name="role_valid"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), primary_key=True)

    user_profile: Mapped[UserProfile] = relationship(back_populates="roles")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        CheckConstraint("length(trim(prompt)) > 0", name="prompt_not_empty"),
        CheckConstraint("length(trim(question_type)) > 0", name="question_type_not_empty"),
        CheckConstraint("length(trim(default_language)) > 0", name="default_language_not_empty"),
        CheckConstraint("time_limit_seconds > 0", name="time_limit_positive"),
        CheckConstraint("display_order >= 0", name="display_order_nonnegative"),
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="question_difficulty_valid"),
        CheckConstraint("points >= 0", name="question_points_nonnegative"),
        UniqueConstraint("assessment_id", "display_order", name="uq_questions_assessment_display_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assessment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False)
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    default_language: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed_languages: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=sql_text("'[]'")
    )
    problem_statement: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    examples: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    answer_options: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=sql_text("'[]'")
    )
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    assessment: Mapped[Assessment] = relationship(back_populates="questions")
    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestCase.display_order",
    )


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (
        CheckConstraint("visibility IN ('public', 'hidden')", name="visibility_valid"),
        CheckConstraint("display_order >= 0", name="display_order_nonnegative"),
        UniqueConstraint("question_id", "display_order", name="uq_test_cases_question_display_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    input_data: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="hidden")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    question: Mapped[Question] = relationship(back_populates="test_cases")


class AssessmentAccessGrant(Base):
    """Persisted authorization created only after a valid restricted code check."""

    __tablename__ = "assessment_access_grants"
    __table_args__ = (Index("ix_assessment_access_grants_expiry", "expires_at"),)

    candidate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE", name="fk_access_grant_candidate"), primary_key=True
    )
    assessment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE", name="fk_access_grant_assessment"), primary_key=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessCodeRateLimit(Base):
    """Persistent per-account throttle for restricted access-code guesses."""

    __tablename__ = "access_code_rate_limits"
    __table_args__ = (CheckConstraint("failed_attempts >= 0", name="rate_failures_nonnegative"),)

    candidate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE", name="fk_code_limit_candidate"), primary_key=True
    )
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentAttempt(Base):
    """A candidate's persisted attempt with server-enforced deadline and status."""

    __tablename__ = "assessment_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("status IN ('in_progress', 'submitted', 'expired')", name="attempt_status_valid"),
        CheckConstraint("execution_status IN ('not_started', 'running', 'completed', 'manual_review', 'unavailable', 'failed')", name="attempt_execution_status_valid"),
        CheckConstraint("score IS NULL OR score >= 0", name="attempt_score_nonnegative"),
        CheckConstraint("max_score IS NULL OR max_score >= 0", name="attempt_max_score_nonnegative"),
        CheckConstraint("score IS NULL OR max_score IS NOT NULL AND score <= max_score", name="attempt_score_not_above_max"),
        CheckConstraint("manual_score IS NULL OR manual_score >= 0", name="attempt_manual_score_nonnegative"),
        CheckConstraint("final_score IS NULL OR final_score >= 0", name="attempt_final_score_nonnegative"),
        CheckConstraint("final_score IS NULL OR max_score IS NOT NULL AND final_score <= max_score", name="attempt_final_score_not_above_max"),
        CheckConstraint("review_status IN ('pending', 'complete', 'not_required')", name="attempt_review_status_valid"),
        UniqueConstraint("candidate_id", "assessment_id", "attempt_number", name="uq_attempt_candidate_number"),
        Index("ix_attempts_candidate_started", "candidate_id", "started_at"),
        Index("ix_attempts_assessment_candidate", "assessment_id", "candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE", name="fk_attempt_candidate"), nullable=False
    )
    assessment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE", name="fk_attempt_assessment"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="in_progress", server_default="in_progress")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started", server_default="not_started")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_required", server_default="not_required")


class AttemptResponse(Base):
    """Saved candidate answer; persistence only, with no execution or scoring."""

    __tablename__ = "attempt_responses"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_attempt_response_question"),
        CheckConstraint(
            "programming_language IS NULL OR programming_language IN ('python', 'c')",
            name="response_language_valid",
        ),
        CheckConstraint("execution_status IN ('not_started', 'completed', 'compile_error', 'runtime_error', 'timeout', 'resource_limit', 'manual_review', 'unavailable', 'failed')", name="response_execution_status_valid"),
        CheckConstraint("score IS NULL OR score >= 0", name="response_score_nonnegative"),
        CheckConstraint("manual_score IS NULL OR manual_score >= 0", name="response_manual_score_nonnegative"),
        CheckConstraint("passed_test_cases IS NULL OR passed_test_cases >= 0", name="response_passed_cases_nonnegative"),
        CheckConstraint("total_test_cases IS NULL OR total_test_cases >= 0", name="response_total_cases_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assessment_attempts.id", ondelete="CASCADE", name="fk_response_attempt"), nullable=False
    )
    question_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE", name="fk_response_question"), nullable=False
    )
    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    programming_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )
    execution_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started", server_default="not_started")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed_test_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_test_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_details: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    manual_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="SET NULL", name="fk_response_reviewer"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FollowUpInterview(Base):
    """Private follow-up interview attached to exactly one submitted attempt."""

    __tablename__ = "follow_up_interviews"
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_follow_up_interviews_attempt"),
        CheckConstraint("status IN ('pending', 'in_progress', 'submitted', 'reviewed')", name="follow_up_status_valid"),
        CheckConstraint("review_score IS NULL OR review_score BETWEEN 0 AND 100", name="follow_up_score_valid"),
        Index("ix_follow_up_candidate", "candidate_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False)
    assessment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())


class FollowUpQuestion(Base):
    """Candidate-facing generated or evaluator-authored follow-up question."""

    __tablename__ = "follow_up_questions"
    __table_args__ = (
        CheckConstraint("origin IN ('ai', 'evaluator')", name="follow_up_origin_valid"),
        CheckConstraint("length(trim(prompt)) > 0", name="follow_up_prompt_nonempty"),
        CheckConstraint("length(answer) <= 20000", name="follow_up_answer_length"),
        Index("ix_follow_up_question_interview", "interview_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    interview_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("follow_up_interviews.id", ondelete="CASCADE"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    answer_locked: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=sql_text("false"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
