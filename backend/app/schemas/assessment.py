"""Validated evaluator assessment request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Difficulty = Literal["easy", "medium", "hard"]
Language = Literal["python", "c"]
QuestionType = Literal["programming", "debugging", "explanation", "multiple-choice"]
AccessMode = Literal["open", "restricted"]
Purpose = Literal["hiring", "practice"]
Visibility = Literal["public", "hidden"]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestCaseInput(RequestModel):
    input_data: str = ""
    expected_output: str = ""
    visibility: Visibility = "hidden"
    display_order: int = Field(default=0, ge=0)


class QuestionInput(RequestModel):
    id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20000)
    question_type: QuestionType = "programming"
    difficulty: Difficulty = "medium"
    points: int = Field(default=0, ge=0, le=10000)
    default_language: Language | None = None
    allowed_languages: list[Language] = Field(default_factory=list, max_length=2)
    time_limit_seconds: int | None = Field(default=None, gt=0, le=86400)
    display_order: int = Field(default=0, ge=0)
    problem_statement: str = Field(default="", max_length=50000)
    examples: str = Field(default="", max_length=20000)
    answer_options: list[str] = Field(default_factory=list, max_length=20)
    correct_answer: str | None = Field(default=None, max_length=20000)
    test_cases: list[TestCaseInput] = Field(default_factory=list, max_length=100)

    @field_validator("title", "prompt")
    @classmethod
    def required_text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain non-whitespace text")
        return value

    @model_validator(mode="after")
    def unique_languages_and_test_case_order(self) -> "QuestionInput":
        if len(set(self.allowed_languages)) != len(self.allowed_languages):
            raise ValueError("allowed_languages cannot contain duplicates")
        orders = [case.display_order for case in self.test_cases]
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("test case display_order values must be contiguous starting at zero")
        return self


class AssessmentDraftInput(RequestModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=50000)
    instructions: str = Field(default="", max_length=50000)
    difficulty: Difficulty = "medium"
    duration_seconds: int = Field(default=3600, ge=60, le=86400)
    allowed_languages: list[Language] = Field(default_factory=lambda: ["python"], min_length=1, max_length=2)
    access_mode: AccessMode = "open"
    purpose: Purpose = "practice"
    max_attempts: int | None = Field(default=None, gt=0, le=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    show_results_after_submission: bool = False
    questions: list[QuestionInput] = Field(default_factory=list, max_length=50)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must contain non-whitespace text")
        return value

    @model_validator(mode="after")
    def validate_settings_and_question_order(self) -> "AssessmentDraftInput":
        if len(set(self.allowed_languages)) != len(self.allowed_languages):
            raise ValueError("allowed_languages cannot contain duplicates")
        if self.starts_at and self.starts_at.tzinfo is None:
            raise ValueError("starts_at must include a timezone")
        if self.ends_at and self.ends_at.tzinfo is None:
            raise ValueError("ends_at must include a timezone")
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        orders = [question.display_order for question in self.questions]
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("question display_order values must be contiguous starting at zero")
        question_ids = [question.id for question in self.questions if question.id is not None]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("question IDs cannot be duplicated")
        return self


class AssessmentSettingsInput(RequestModel):
    """Settings replacement separate from the question collection."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=50000)
    instructions: str = Field(default="", max_length=50000)
    difficulty: Difficulty = "medium"
    duration_seconds: int = Field(default=3600, ge=60, le=86400)
    allowed_languages: list[Language] = Field(default_factory=lambda: ["python"], min_length=1, max_length=2)
    access_mode: AccessMode = "open"
    purpose: Purpose = "practice"
    max_attempts: int | None = Field(default=None, gt=0, le=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    show_results_after_submission: bool = False

    @model_validator(mode="after")
    def validate_settings(self) -> "AssessmentSettingsInput":
        if not self.title.strip():
            raise ValueError("title must contain non-whitespace text")
        if len(set(self.allowed_languages)) != len(self.allowed_languages):
            raise ValueError("allowed_languages cannot contain duplicates")
        if self.starts_at and self.starts_at.tzinfo is None:
            raise ValueError("starts_at must include a timezone")
        if self.ends_at and self.ends_at.tzinfo is None:
            raise ValueError("ends_at must include a timezone")
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        return self


class AssessmentUpdateInput(AssessmentSettingsInput):
    questions: list[QuestionInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_questions(self) -> "AssessmentUpdateInput":
        orders = [question.display_order for question in self.questions]
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("question display_order values must be contiguous starting at zero")
        question_ids = [question.id for question in self.questions if question.id is not None]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("question IDs cannot be duplicated")
        return self


class TestCaseResponse(BaseModel):
    id: UUID
    input_data: str
    expected_output: str
    visibility: Visibility
    display_order: int


class QuestionResponse(BaseModel):
    id: UUID
    title: str
    prompt: str
    question_type: str
    difficulty: str
    points: int
    default_language: str
    allowed_languages: list[str]
    time_limit_seconds: int
    display_order: int
    problem_statement: str
    examples: str
    answer_options: list[str]
    correct_answer: str | None
    test_cases: list[TestCaseResponse]


class AssessmentSummary(BaseModel):
    id: UUID
    title: str
    description: str
    instructions: str
    status: str
    difficulty: str
    duration_seconds: int
    allowed_languages: list[str]
    access_mode: AccessMode
    purpose: str | None
    max_attempts: int | None
    starts_at: datetime | None
    ends_at: datetime | None
    published_at: datetime | None
    show_results_after_submission: bool
    question_count: int
    created_at: datetime
    updated_at: datetime


class AssessmentDetail(AssessmentSummary):
    questions: list[QuestionResponse]
    access_code: str | None = None


class AssessmentListResponse(BaseModel):
    assessments: list[AssessmentSummary]


class EvaluationQuestionResult(BaseModel):
    question_id: UUID
    question_title: str
    question_type: str
    question_prompt: str
    max_points: int
    response_text: str | None
    programming_language: str | None
    execution_status: str
    score: int | None
    passed_test_cases: int | None
    total_test_cases: int | None
    execution_details: list[dict[str, object]] | None
    manual_score: int | None
    manual_feedback: str | None
    reviewed_at: datetime | None
    review_eligible: bool


class EvaluationAttemptResult(BaseModel):
    attempt_id: UUID
    candidate_id: UUID
    candidate_display_name: str | None
    attempt_number: int
    status: str
    execution_status: str
    started_at: datetime
    submitted_at: datetime | None
    score: int | None
    max_score: int | None
    manual_score: int | None
    final_score: int | None
    review_status: Literal["pending", "complete", "not_required"]
    responses: list[EvaluationQuestionResult]


class AssessmentResultsResponse(BaseModel):
    assessment_id: UUID
    attempts: list[EvaluationAttemptResult]
    total: int
    limit: int
    offset: int


class ManualReviewInput(RequestModel):
    score: int = Field(ge=0, le=10000)
    feedback: str | None = Field(default=None, max_length=10000)


class QuestionOrderInput(RequestModel):
    question_ids: list[UUID] = Field(min_length=1, max_length=50)


class AccessCodeResponse(BaseModel):
    assessment_id: UUID
    access_code: str
