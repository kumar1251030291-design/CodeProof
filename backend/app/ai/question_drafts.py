"""Provider abstraction and strict parsing for unsaved assessment drafts."""

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import Field, ValidationError, model_validator

from app.core.config import settings
from app.schemas.assessment import (
    Difficulty,
    Language,
    Purpose,
    QuestionInput,
    QuestionType,
    RequestModel,
    TestCaseInput,
)

MAX_GENERATION_QUESTIONS = 8
MAX_PROVIDER_OUTPUT_CHARS = 400_000


class GenerationRequest(RequestModel):
    topic: str = Field(min_length=1, max_length=500)
    purpose: Purpose
    experience_level: str = Field(min_length=1, max_length=80)
    difficulty: Difficulty
    programming_languages: list[Language] = Field(min_length=1, max_length=2)
    question_count: int = Field(ge=1, le=MAX_GENERATION_QUESTIONS)
    question_types: list[QuestionType] = Field(min_length=1, max_length=4)
    duration_seconds: int = Field(ge=60, le=86400)
    job_role: str | None = Field(default=None, max_length=120)
    skills: str | None = Field(default=None, max_length=2000)
    difficulty_mix: str | None = Field(default=None, max_length=300)
    learning_objectives: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_choices(self) -> "GenerationRequest":
        if not self.topic.strip() or not self.experience_level.strip():
            raise ValueError("topic and experience_level must not be blank")
        if len(set(self.programming_languages)) != len(self.programming_languages):
            raise ValueError("programming_languages cannot contain duplicates")
        if len(set(self.question_types)) != len(self.question_types):
            raise ValueError("question_types cannot contain duplicates")
        return self


class ProposedPublicCase(RequestModel):
    input_data: str = Field(default="", max_length=20000)
    expected_output: str = Field(default="", max_length=20000)


class ProposedQuestion(RequestModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20000)
    question_type: QuestionType
    difficulty: Difficulty
    points: int = Field(ge=0, le=10000)
    problem_statement: str = Field(default="", max_length=50000)
    examples: str = Field(default="", max_length=20000)
    allowed_languages: list[Language] = Field(default_factory=list, max_length=2)
    time_limit_seconds: int = Field(ge=60, le=86400)
    answer_options: list[str] = Field(default_factory=list, max_length=20)
    correct_answer: str | None = Field(default=None, max_length=20000)
    public_test_cases: list[ProposedPublicCase] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_question_content(self) -> "ProposedQuestion":
        if not self.title.strip() or not self.prompt.strip():
            raise ValueError("question title and prompt must not be blank")
        if len(set(self.allowed_languages)) != len(self.allowed_languages):
            raise ValueError("question languages cannot contain duplicates")
        if self.question_type in {"programming", "debugging"} and not self.problem_statement.strip():
            raise ValueError("coding questions require a problem statement")
        if self.question_type == "multiple-choice":
            options = [option.strip() for option in self.answer_options]
            if len(options) < 2 or len(set(options)) != len(options):
                raise ValueError("multiple-choice questions require at least two unique options")
            if not self.correct_answer or self.correct_answer.strip() not in options:
                raise ValueError("multiple-choice correct_answer must match one answer option")
        elif self.answer_options or self.correct_answer is not None:
            raise ValueError("answer keys are only supported for multiple-choice questions")
        if self.question_type not in {"programming", "debugging"} and self.public_test_cases:
            raise ValueError("public test cases are only supported for coding questions")
        return self


class ProposedAssessment(RequestModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=50000)
    instructions: str = Field(default="", max_length=50000)
    questions: list[ProposedQuestion] = Field(min_length=1, max_length=MAX_GENERATION_QUESTIONS)

    @model_validator(mode="after")
    def validate_title(self) -> "ProposedAssessment":
        if not self.title.strip():
            raise ValueError("assessment title must not be blank")
        return self


class GeneratedQuestion(RequestModel):
    title: str
    prompt: str
    question_type: QuestionType
    difficulty: Difficulty
    points: int
    default_language: Language
    allowed_languages: list[Language]
    time_limit_seconds: int
    display_order: int
    problem_statement: str
    examples: str
    answer_options: list[str]
    correct_answer: str | None
    test_cases: list[TestCaseInput]


class GeneratedAssessment(RequestModel):
    title: str
    description: str
    instructions: str
    questions: list[GeneratedQuestion]


class ProviderError(Exception):
    """Base class for safe, non-secret provider failures."""


class ProviderNotConfigured(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class ProviderTimedOut(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderMalformedOutput(ProviderError):
    pass


class QuestionDraftProvider(Protocol):
    def generate(self, request: GenerationRequest) -> str: ...


class OpenAIQuestionDraftProvider:
    """Small Chat Completions adapter; credentials remain in backend settings."""

    def generate(self, request: GenerationRequest) -> str:
        api_key = settings.openai_api_key
        if not api_key:
            raise ProviderNotConfigured
        if settings.ai_provider.lower() != "openai":
            raise ProviderNotConfigured

        instructions = (
            "Create editable coding assessment draft suggestions as one JSON object with keys "
            "title, description, instructions, questions. Each question must use keys title, prompt, "
            "question_type, difficulty, points, problem_statement, examples, allowed_languages, "
            "time_limit_seconds, answer_options, correct_answer, public_test_cases. Each public_test_cases "
            "item has input_data and expected_output. Do not include hidden cases, ownership, publication, "
            "or persistence fields. For non-multiple-choice questions use empty answer_options and null "
            "correct_answer. Public examples and test cases are unverified suggestions."
        )
        body = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": request.model_dump_json()},
            ],
            "response_format": {"type": "json_object"},
            "store": False,
        }
        encoded = json.dumps(body).encode("utf-8")
        http_request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=encoded,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=max(5, min(settings.ai_timeout_seconds, 60))) as response:
                raw = response.read(MAX_PROVIDER_OUTPUT_CHARS * 4 + 1)
        except HTTPError as error:
            if error.code == 429:
                raise ProviderRateLimited from None
            if error.code in {408, 504}:
                raise ProviderTimedOut from None
            raise ProviderUnavailable from None
        except TimeoutError:
            raise ProviderTimedOut from None
        except (URLError, OSError):
            raise ProviderUnavailable from None

        if len(raw) > MAX_PROVIDER_OUTPUT_CHARS * 4:
            raise ProviderMalformedOutput
        try:
            envelope = json.loads(raw)
            content = envelope["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content) > MAX_PROVIDER_OUTPUT_CHARS:
                raise ValueError("invalid content")
            return content
        except (ValueError, TypeError, KeyError, IndexError):
            raise ProviderMalformedOutput from None


def parse_generated_assessment(raw: str, request: GenerationRequest) -> GeneratedAssessment:
    """Treat provider output as untrusted and enforce builder schema constraints."""
    if len(raw) > MAX_PROVIDER_OUTPUT_CHARS:
        raise ProviderMalformedOutput
    try:
        proposed = ProposedAssessment.model_validate_json(raw)
        if len(proposed.questions) != request.question_count:
            raise ValueError("question count mismatch")
        generated_questions: list[GeneratedQuestion] = []
        for index, question in enumerate(proposed.questions):
            if question.question_type not in request.question_types:
                raise ValueError("unsupported question type")
            if question.allowed_languages and not set(question.allowed_languages).issubset(request.programming_languages):
                raise ValueError("unsupported question language")
            test_cases = [
                TestCaseInput(input_data=case.input_data, expected_output=case.expected_output,
                              visibility="public", display_order=case_index)
                for case_index, case in enumerate(question.public_test_cases)
            ]
            languages = question.allowed_languages or request.programming_languages
            normalized = QuestionInput(
                title=question.title,
                prompt=question.prompt,
                question_type=question.question_type,
                difficulty=question.difficulty,
                points=question.points,
                default_language=languages[0],
                allowed_languages=languages,
                time_limit_seconds=question.time_limit_seconds,
                display_order=index,
                problem_statement=question.problem_statement,
                examples=question.examples,
                answer_options=question.answer_options,
                correct_answer=question.correct_answer,
                test_cases=test_cases,
            )
            generated_questions.append(GeneratedQuestion(
                title=normalized.title,
                prompt=normalized.prompt,
                question_type=normalized.question_type,
                difficulty=normalized.difficulty,
                points=normalized.points,
                default_language=normalized.default_language or languages[0],
                allowed_languages=normalized.allowed_languages,
                time_limit_seconds=normalized.time_limit_seconds or request.duration_seconds,
                display_order=index,
                problem_statement=normalized.problem_statement,
                examples=normalized.examples,
                answer_options=normalized.answer_options,
                correct_answer=normalized.correct_answer,
                test_cases=normalized.test_cases,
            ))
        return GeneratedAssessment(
            title=proposed.title.strip(),
            description=proposed.description,
            instructions=proposed.instructions,
            questions=generated_questions,
        )
    except (ValidationError, ValueError, TypeError):
        raise ProviderMalformedOutput from None
