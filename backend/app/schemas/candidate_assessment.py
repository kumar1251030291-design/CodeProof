"""Candidate-safe assessment and attempt payloads."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CandidateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicExample(BaseModel):
    input_data: str
    expected_output: str
    display_order: int


class CandidateQuestion(BaseModel):
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
    public_examples: list[PublicExample]


class CandidateAssessmentSummary(BaseModel):
    id: UUID
    title: str
    description: str
    instructions: str
    difficulty: str
    duration_seconds: int
    allowed_languages: list[str]
    question_count: int
    starts_at: datetime | None
    ends_at: datetime | None
    max_attempts: int | None


class CandidateAssessmentDetail(CandidateAssessmentSummary):
    questions: list[CandidateQuestion]


class CandidateAssessmentList(BaseModel):
    assessments: list[CandidateAssessmentSummary]


class AccessCodeInput(CandidateModel):
    access_code: str = Field(min_length=1, max_length=256)


class RestrictedAccessResponse(BaseModel):
    assessment: CandidateAssessmentDetail
    grant_expires_at: datetime


AttemptStatus = Literal["in_progress", "submitted", "expired"]


class AttemptResponseView(BaseModel):
    question_id: UUID
    response_text: str
    programming_language: str | None
    saved_at: datetime
    execution_status: str = "not_started"
    score: int | None = None


class AssessmentAttemptView(BaseModel):
    id: UUID
    assessment_id: UUID
    assessment_title: str
    attempt_number: int
    started_at: datetime
    deadline_at: datetime
    status: AttemptStatus
    submitted_at: datetime | None
    execution_status: str = "not_started"
    score: int | None = None
    max_score: int | None = None
    responses: list[AttemptResponseView] = Field(default_factory=list)


class AssessmentAttemptList(BaseModel):
    attempts: list[AssessmentAttemptView]


class CandidateResponseInput(CandidateModel):
    response_text: str = Field(max_length=100000)
    programming_language: Literal["python", "c"] | None = None
