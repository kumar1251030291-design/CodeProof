from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.ai.question_drafts import (
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderTimedOut,
    ProviderUnavailable,
    parse_generated_assessment,
)
from app.api.ai_generation import ai_generation_limiter, get_question_draft_provider
from app.core.auth import get_current_identity
from app.core.config import settings
from app.core.database import Base, get_db_session
from app.models import Assessment

TEST_URL = "https://ai-test.supabase.co"
TEST_SECRET = "test-only-ai-auth-key-for-local-unit-tests"


class FakeProvider:
    def __init__(self, output: str | Exception):
        self.output = output
        self.calls = 0

    def generate(self, _request):
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


@pytest.fixture
def ai_client(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    ai_generation_limiter.clear()
    monkeypatch.setattr(settings, "supabase_url", TEST_URL)
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_SECRET)
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    monkeypatch.setattr(settings, "evaluator_user_ids", set())
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    main.app.dependency_overrides[get_db_session] = override_db
    with TestClient(main.app) as client:
        yield client, factory
    main.app.dependency_overrides.pop(get_db_session, None)
    main.app.dependency_overrides.pop(get_question_draft_provider, None)
    main.app.dependency_overrides.pop(get_current_identity, None)
    ai_generation_limiter.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def token(user_id: UUID) -> str:
    settings.evaluator_user_ids.add(user_id)
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id), "aud": "authenticated", "iss": f"{TEST_URL}/auth/v1",
            "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()),
        }, TEST_SECRET, algorithm="HS256",
    )


def request_body(**updates: object) -> dict[str, object]:
    return {
        "topic": "Two pointer algorithms", "purpose": "hiring", "experience_level": "mid-level",
        "difficulty": "medium", "programming_languages": ["python", "c"], "question_count": 1,
        "question_types": ["programming"], "duration_seconds": 3600,
        "job_role": "Backend engineer", "skills": "arrays", "learning_objectives": "complexity",
        **updates,
    }


def valid_output(**question_updates: object) -> str:
    question = {
        "title": "Pair sum", "prompt": "Return indices for the target.", "question_type": "programming",
        "difficulty": "medium", "points": 10, "problem_statement": "Given nums and target, find two values.",
        "examples": "Input: [2, 7], 9\nOutput: [0, 1]", "allowed_languages": ["python"],
        "time_limit_seconds": 900, "answer_options": [], "correct_answer": None,
        "public_test_cases": [{"input_data": "2 7 9", "expected_output": "0 1"}],
        **question_updates,
    }
    return json.dumps({"title": "Array fundamentals", "description": "Evaluate arrays.",
                       "instructions": "Explain your approach.", "questions": [question]})


def test_generation_rejects_unauthenticated_users_and_keeps_health_public(ai_client) -> None:
    client, _ = ai_client
    assert client.post("/api/v1/evaluator/ai/question-drafts", json=request_body()).status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200


def test_missing_provider_key_returns_clear_safe_configuration_error(ai_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = ai_client
    monkeypatch.setattr(settings, "openai_api_key", None)
    response = client.post(
        "/api/v1/evaluator/ai/question-drafts",
        headers={"Authorization": f"Bearer {token(uuid4())}"}, json=request_body(),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AI draft generation is not configured"
    assert TEST_SECRET not in response.text


def test_generation_requires_evaluator_role(ai_client) -> None:
    client, _ = ai_client
    from app.core.auth import AuthenticatedIdentity
    from app.models import UserProfile

    identity = AuthenticatedIdentity(profile=UserProfile(id=uuid4()), email=None, roles=("candidate",))
    ai_client[0].app.dependency_overrides[get_current_identity] = lambda: identity
    provider = FakeProvider(valid_output())
    client.app.dependency_overrides[get_question_draft_provider] = lambda: provider
    response = client.post("/api/v1/evaluator/ai/question-drafts", json=request_body())
    assert response.status_code == 403
    assert provider.calls == 0


def test_generation_returns_validated_public_draft_without_persisting(ai_client) -> None:
    client, factory = ai_client
    provider = FakeProvider(valid_output())
    client.app.dependency_overrides[get_question_draft_provider] = lambda: provider
    response = client.post(
        "/api/v1/evaluator/ai/question-drafts",
        headers={"Authorization": f"Bearer {token(uuid4())}"},
        json=request_body(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["questions"][0]["points"] == 10
    assert body["questions"][0]["test_cases"][0]["visibility"] == "public"
    assert "assessment_id" not in body and "owner_id" not in body
    with factory() as session:
        assert session.scalar(select(Assessment.id)) is None


def test_ai_generation_has_process_local_per_user_limit(ai_client) -> None:
    client, _ = ai_client
    user_id = uuid4()
    headers = {"Authorization": f"Bearer {token(user_id)}"}
    provider = FakeProvider(valid_output())
    client.app.dependency_overrides[get_question_draft_provider] = lambda: provider
    for _ in range(5):
        assert client.post("/api/v1/evaluator/ai/question-drafts", headers=headers, json=request_body()).status_code == 200
    limited = client.post("/api/v1/evaluator/ai/question-drafts", headers=headers, json=request_body())
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert provider.calls == 5


@pytest.mark.parametrize(
    ("provider_error", "status_code"),
    [
        (ProviderNotConfigured(), 503), (ProviderRateLimited(), 429), (ProviderTimedOut(), 504),
        (ProviderUnavailable(), 502),
    ],
)
def test_provider_failures_are_safe(ai_client, provider_error: Exception, status_code: int) -> None:
    client, _ = ai_client
    client.app.dependency_overrides[get_question_draft_provider] = lambda: FakeProvider(provider_error)
    response = client.post(
        "/api/v1/evaluator/ai/question-drafts",
        headers={"Authorization": f"Bearer {token(uuid4())}"}, json=request_body(),
    )
    assert response.status_code == status_code
    assert "test-only-ai-auth-key" not in response.text
    assert "Bearer" not in response.text


@pytest.mark.parametrize(
    "broken",
    [
        "not-json",
        valid_output(question_type="essay", points=10),
        valid_output(points=10001),
        valid_output(owner_id=str(uuid4())),
        valid_output(public_test_cases=[{"input_data": "x", "expected_output": "y", "visibility": "hidden"}]),
    ],
)
def test_malformed_or_unsafe_provider_output_is_rejected(ai_client, broken: str) -> None:
    client, _ = ai_client
    client.app.dependency_overrides[get_question_draft_provider] = lambda: FakeProvider(broken)
    response = client.post(
        "/api/v1/evaluator/ai/question-drafts",
        headers={"Authorization": f"Bearer {token(uuid4())}"}, json=request_body(),
    )
    assert response.status_code == 502
    assert "owner_id" not in response.text


def test_excessive_request_count_is_rejected_before_provider(ai_client) -> None:
    client, _ = ai_client
    provider = FakeProvider(valid_output())
    client.app.dependency_overrides[get_question_draft_provider] = lambda: provider
    response = client.post(
        "/api/v1/evaluator/ai/question-drafts",
        headers={"Authorization": f"Bearer {token(uuid4())}"},
        json=request_body(question_count=9),
    )
    assert response.status_code == 422
    assert provider.calls == 0


def test_parser_validates_choice_keys_and_requested_question_type() -> None:
    from app.ai.question_drafts import GenerationRequest, ProviderMalformedOutput

    request = GenerationRequest.model_validate(request_body(question_types=["multiple-choice"]))
    raw = valid_output(
        question_type="multiple-choice", problem_statement="", answer_options=["A", "B"],
        correct_answer="C", public_test_cases=[],
    )
    with pytest.raises(ProviderMalformedOutput):
        parse_generated_assessment(raw, request)

