"""Bounded, client-supplied context for candidate AI assistance."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.assessment import RequestModel

MAX_ASSISTANT_INPUT_CHARS = 16_000


class AssistantTurn(RequestModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=1_200)


class CandidateAssistanceRequest(RequestModel):
    assessment_id: UUID
    attempt_id: UUID
    question_id: UUID
    message: str = Field(min_length=1, max_length=1_600)
    history: list[AssistantTurn] = Field(default_factory=list, max_length=8)
    include_code: bool = False
    code: str | None = Field(default=None, max_length=8_000)

    @model_validator(mode="after")
    def validate_assistant_context(self) -> "CandidateAssistanceRequest":
        if not self.message.strip():
            raise ValueError("message must not be blank")
        if self.code is not None and not self.include_code:
            raise ValueError("code may only be sent when include_code is true")
        total = len(self.message) + sum(len(turn.text) for turn in self.history)
        if self.include_code and self.code:
            total += len(self.code)
        if total > MAX_ASSISTANT_INPUT_CHARS:
            raise ValueError("assistant context is too large")
        return self


class CandidateAssistanceResponse(RequestModel):
    message: str = Field(min_length=1, max_length=6_000)
