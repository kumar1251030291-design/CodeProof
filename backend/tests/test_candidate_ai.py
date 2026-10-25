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
from urllib.error import HTTPError

from app import main
from app.ai.candidate_assistant import (
    AssistantMalformedOutput,
    AssistantNotConfigured,
    AssistantRateLimited,
    AssistantTimedOut,
    AssistantUnavailable,
    CandidateQuestionContext,
    GeminiCandidateAssistant,
)
from app.api.candidate_ai import candidate_assistance_limiter, get_candidate_assistant_provider
from app.core.auth import get_current_identity
from app.core.config import settings
from app.core.database import Base, get_db_session
from app.models import (
    Assessment,
    AssessmentAttempt,
    AttemptResponse,
    Question,
    TestCase as CaseModel,
    UserProfile,
)
from app.schemas.candidate_assistant import CandidateAssistanceRequest

TEST_URL = "https://candidate-ai-test.supabase.co"
TEST_SECRET = "test-only-candidate-ai-auth-key-long-enough-for-hmac"
HIDDEN_INPUT = "PRIVATE_HIDDEN_CASE_7fbd"
HIDDEN_OUTPUT = "PRIVATE_EXPECTED_OUTPUT_b731"


class FakeCandidateAssistant:
    def __init__(self, result: str | Exception = "Consider tracing the values step by step.") -> None:
        self.result = result
        self.calls: list[tuple[CandidateQuestionContext, CandidateAssistanceRequest]] = []

    def respond(self, question, request):
        self.calls.append((question, request))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def candidate_ai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    candidate_assistance_limiter.clear()
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
    main.app.dependency_overrides.pop(get_candidate_assistant_provider, None)
    main.app.dependency_overrides.pop(get_current_identity, None)
    candidate_assistance_limiter.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_token(user_id: UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "iss": f"{TEST_URL}/auth/v1",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        TEST_SECRET,
        algorithm="HS256",
    )


def make_attempt(
    factory: sessionmaker[Session],
    candidate_id: UUID,
    *,
    status: str = "in_progress",
    deadline: datetime | None = None,
) -> dict[str, UUID]:
    assessment_id, question_id, attempt_id = uuid4(), uuid4(), uuid4()
    with factory() as session:
        session.add(UserProfile(id=candidate_id))
        session.add(Assessment(
            id=assessment_id,
            title="Candidate visible assessment",
            description="",
            instructions="",
            status="published",
            access_mode="public",
        ))
        session.add(Question(
            id=question_id,
            assessment_id=assessment_id,
            title="Array pairs",
            prompt="Return the indices of a pair whose sum matches the target.",
            question_type="programming",
            difficulty="easy",
            points=10,
            default_language="python",
            allowed_languages=["python"],
            time_limit_seconds=900,
            display_order=0,
            problem_statement="Explain your approach and return the two indices.",
            examples="Input: [2, 7], target 9. Output: [0, 1].",
        ))
        session.add(AssessmentAttempt(
            id=attempt_id,
            candidate_id=candidate_id,
            assessment_id=assessment_id,
            attempt_number=1,
            deadline_at=deadline or datetime.now(UTC) + timedelta(minutes=30),
            status=status,
            score=3,
            max_score=10,
        ))
        session.flush()
        session.add(CaseModel(
            id=uuid4(), question_id=question_id, input_data=HIDDEN_INPUT,
            expected_output=HIDDEN_OUTPUT, visibility="hidden", display_order=0,
        ))
        session.add(AttemptResponse(
            id=uuid4(), attempt_id=attempt_id, question_id=question_id,
            response_text="candidate's saved answer", score=2,
        ))
        session.commit()
    return {"assessment_id": assessment_id, "question_id": question_id, "attempt_id": attempt_id}


def request_payload(ids: dict[str, UUID], **overrides):
    return {
        "assessment_id": str(ids["assessment_id"]),
        "attempt_id": str(ids["attempt_id"]),
        "question_id": str(ids["question_id"]),
        "message": "Can you give me a hint?",
        **overrides,
    }


def auth_headers(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id)}"}


def install_fake(client: TestClient, fake: FakeCandidateAssistant) -> None:
    client.app.dependency_overrides[get_candidate_assistant_provider] = lambda: fake


def test_assistance_requires_authentication(candidate_ai_client) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    fake = FakeCandidateAssistant()
    install_fake(client, fake)

    response = client.post("/api/v1/candidate/ai/assistance", json=request_payload(ids))

    assert response.status_code == 401
    assert fake.calls == []


def test_candidate_cannot_use_another_candidates_attempt(candidate_ai_client) -> None:
    client, factory = candidate_ai_client
    caller_id, owner_id = uuid4(), uuid4()
    ids = make_attempt(factory, owner_id)
    fake = FakeCandidateAssistant()
    install_fake(client, fake)

    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(caller_id),
        json=request_payload(ids),
    )

    assert response.status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize(
    ("status", "deadline", "expected"),
    [
        ("submitted", datetime.now(UTC) + timedelta(minutes=10), 409),
        ("expired", datetime.now(UTC) + timedelta(minutes=10), 409),
        ("in_progress", datetime.now(UTC) - timedelta(seconds=1), 409),
    ],
)
def test_ineligible_attempts_are_rejected_without_state_changes(
    candidate_ai_client, status: str, deadline: datetime, expected: int
) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id, status=status, deadline=deadline)
    fake = FakeCandidateAssistant()
    install_fake(client, fake)

    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids),
    )

    assert response.status_code == expected
    assert fake.calls == []
    with factory() as session:
        attempt = session.get(AssessmentAttempt, ids["attempt_id"])
        assert attempt is not None and attempt.status == status and attempt.score == 3


def test_missing_gemini_credentials_return_safe_configuration_error(
    candidate_ai_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Candidate AI assistance is not configured"
    assert TEST_SECRET not in response.text


@pytest.mark.parametrize(
    ("provider_error", "expected"),
    [
        (AssistantRateLimited(), 429),
        (AssistantTimedOut(), 504),
        (AssistantUnavailable(), 502),
        (AssistantMalformedOutput(), 502),
        (AssistantNotConfigured(), 503),
    ],
)
def test_provider_failures_are_safely_mapped(candidate_ai_client, provider_error: Exception, expected: int) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    install_fake(client, FakeCandidateAssistant(provider_error))

    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids),
    )

    assert response.status_code == expected
    assert TEST_SECRET not in response.text
    assert "Bearer" not in response.text
    assert HIDDEN_INPUT not in response.text and HIDDEN_OUTPUT not in response.text


def test_request_and_field_limits_reject_oversized_input(candidate_ai_client) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    fake = FakeCandidateAssistant()
    install_fake(client, fake)

    too_large_body = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids, message="x" * 20_500),
    )
    too_long_message = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids, message="x" * 1_601),
    )

    assert too_large_body.status_code == 413
    assert too_long_message.status_code == 422
    assert fake.calls == []


def test_assistance_has_per_candidate_rate_limit(candidate_ai_client) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    fake = FakeCandidateAssistant()
    install_fake(client, fake)

    responses = [
        client.post("/api/v1/candidate/ai/assistance", headers=auth_headers(user_id), json=request_payload(ids))
        for _ in range(6)
    ]

    assert [response.status_code for response in responses] == [200] * 5 + [429]
    assert responses[-1].headers.get("Retry-After")
    assert len(fake.calls) == 5


def test_real_provider_context_excludes_hidden_tests_and_only_shares_opted_in_code(
    candidate_ai_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    monkeypatch.setattr(settings, "gemini_api_key", "test-only-gemini-key")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int) -> bytes:
            payload = {"candidates": [{"content": {"parts": [{"text": "Try using a map to remember earlier values."}]}}]}
            return json.dumps(payload).encode()[:size]

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.ai.candidate_assistant.urlopen", fake_urlopen)

    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids),
    )

    assert response.status_code == 200, response.text
    assert response.json()["message"].startswith("Try using a map")
    serialized = json.dumps(captured["payload"])
    assert HIDDEN_INPUT not in serialized and HIDDEN_OUTPUT not in serialized
    assert "candidate's saved answer" not in serialized
    assert "current code" not in serialized
    assert captured["timeout"] == settings.gemini_timeout_seconds
    assert "systemInstruction" in captured["payload"]
    with factory() as session:
        attempt = session.get(AssessmentAttempt, ids["attempt_id"])
        saved = session.scalar(select(AttemptResponse).where(AttemptResponse.attempt_id == ids["attempt_id"]))
        assert attempt is not None and attempt.status == "in_progress" and attempt.score == 3
        assert saved is not None and saved.response_text == "candidate's saved answer" and saved.score == 2


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (TimeoutError("private timeout"), 504),
        (HTTPError("https://provider.invalid", 429, "private quota detail", {}, None), 429),
        (OSError("private provider detail"), 502),
    ],
)
def test_gemini_http_timeouts_quota_and_failures_are_sanitized(
    candidate_ai_client, monkeypatch: pytest.MonkeyPatch, failure: Exception, expected: int
) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    monkeypatch.setattr(settings, "gemini_api_key", "test-only-gemini-key")

    def fake_urlopen(_request, timeout):
        raise failure

    monkeypatch.setattr("app.ai.candidate_assistant.urlopen", fake_urlopen)
    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids),
    )

    assert response.status_code == expected
    assert "private" not in response.text
    assert "test-only-gemini-key" not in response.text


def test_malformed_and_oversized_provider_responses_are_rejected(candidate_ai_client, monkeypatch) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    monkeypatch.setattr(settings, "gemini_api_key", "test-only-gemini-key")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int) -> bytes:
            return b"not-json"[:size]

    monkeypatch.setattr("app.ai.candidate_assistant.urlopen", lambda *_args, **_kwargs: FakeResponse())
    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "AI provider returned an invalid response"

    install_fake(client, FakeCandidateAssistant("x" * 6_001))
    oversized = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids),
    )
    assert oversized.status_code == 502


def test_client_cannot_submit_a_candidate_identity(candidate_ai_client) -> None:
    client, factory = candidate_ai_client
    user_id = uuid4()
    ids = make_attempt(factory, user_id)
    fake = FakeCandidateAssistant()
    install_fake(client, fake)
    response = client.post(
        "/api/v1/candidate/ai/assistance",
        headers=auth_headers(user_id),
        json=request_payload(ids, candidate_id=str(uuid4())),
    )
    assert response.status_code == 422
    assert fake.calls == []
