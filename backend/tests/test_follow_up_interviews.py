from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError
from uuid import UUID, uuid4

import jwt
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.api.follow_up_interviews import generation_limiter
from app.core.config import settings
from app.core.database import Base, get_db_session
from app.models import Assessment, AssessmentAttempt, AttemptResponse, FollowUpInterview, Question, UserProfile

TEST_URL = "https://follow-up-test.supabase.co"
TEST_SECRET = "test-only-follow-up-auth-key-never-use-in-production"


@pytest.fixture
def interview_client(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    generation_limiter.clear()
    monkeypatch.setattr(settings, "supabase_url", TEST_URL)
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_SECRET)
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
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
    main.app.dependency_overrides.pop("get_current_identity", None)
    generation_limiter.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def token(user_id: UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode({"sub": str(user_id), "aud": "authenticated", "iss": f"{TEST_URL}/auth/v1", "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp())}, TEST_SECRET, algorithm="HS256")


def create_submitted_attempt(factory: sessionmaker[Session], owner_id: UUID) -> UUID:
    assessment_id, attempt_id, question_id = uuid4(), uuid4(), uuid4()
    with factory() as session:
        session.add(UserProfile(id=owner_id))
        session.add(Assessment(id=assessment_id, title="Arrays", description="", instructions="", status="published", access_mode="public", owner_id=owner_id))
        session.add(Question(id=question_id, assessment_id=assessment_id, title="Pairs", prompt="Find a pair summing to the target.", question_type="programming", difficulty="easy", points=10, default_language="python", allowed_languages=["python"], time_limit_seconds=600, display_order=0, problem_statement="Find a pair."))
        session.add(AssessmentAttempt(id=attempt_id, candidate_id=owner_id, assessment_id=assessment_id, attempt_number=1, deadline_at=datetime.now(UTC), status="submitted", submitted_at=datetime.now(UTC), score=5, max_score=10))
        session.flush()
        session.add(AttemptResponse(attempt_id=attempt_id, question_id=question_id, response_text="def solve(): return []", programming_language="python", execution_status="unavailable"))
        session.commit()
    return attempt_id


def test_generate_retry_resume_and_finalize_are_idempotent_and_do_not_change_score(interview_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, factory = interview_client
    candidate_id = uuid4()
    attempt_id = create_submitted_attempt(factory, candidate_id)
    monkeypatch.setattr("app.api.follow_up_interviews._generate_questions", lambda _payload: ["Why use this approach?", "What is its complexity?", "Which edge case matters?"])
    headers = {"Authorization": f"Bearer {token(candidate_id)}"}
    path = f"/api/v1/candidate/attempts/{attempt_id}/follow-up"
    generated = client.post(path + "/generate", headers=headers)
    assert generated.status_code == 200
    assert len(generated.json()["questions"]) == 3
    assert client.post(path + "/generate", headers=headers).json()["id"] == generated.json()["id"]
    question = generated.json()["questions"][0]
    assert client.put(f"{path}/questions/{question['id']}", headers=headers, json={"answer": "Use a hash map."}).status_code == 200
    assert client.get(path, headers=headers).json()["questions"][0]["answer"] == "Use a hash map."
    assert client.post(path + "/submit", headers=headers).status_code == 422
    for item in generated.json()["questions"]:
        client.put(f"{path}/questions/{item['id']}", headers=headers, json={"answer": "Reasoned answer"})
    submitted = client.post(path + "/submit", headers=headers)
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    original_submitted_at = submitted.json()["submitted_at"]
    repeated = client.post(path + "/submit", headers=headers).json()["submitted_at"]
    assert datetime.fromisoformat(repeated).replace(tzinfo=None) == datetime.fromisoformat(original_submitted_at).replace(tzinfo=None)
    assert client.put(f"{path}/questions/{question['id']}", headers=headers, json={"answer": "changed"}).status_code == 409
    with factory() as session:
        attempt = session.get(AssessmentAttempt, attempt_id)
        assert attempt.score == 5 and attempt.final_score is None


def test_candidate_and_evaluator_scope_and_private_notes(interview_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, factory = interview_client
    candidate_id, other_id, evaluator_id = uuid4(), uuid4(), uuid4()
    attempt_id = create_submitted_attempt(factory, candidate_id)
    monkeypatch.setattr("app.api.follow_up_interviews._generate_questions", lambda _payload: ["Explain the trade-off."])
    candidate_headers = {"Authorization": f"Bearer {token(candidate_id)}"}
    other_headers = {"Authorization": f"Bearer {token(other_id)}"}
    evaluator_headers = {"Authorization": f"Bearer {token(evaluator_id)}"}
    candidate_path = f"/api/v1/candidate/attempts/{attempt_id}/follow-up"
    assert client.post(candidate_path + "/generate", headers=candidate_headers).status_code == 200
    assert client.get(candidate_path, headers=other_headers).status_code == 404
    evaluator_path = f"/api/v1/evaluator/assessments/{uuid4()}/attempts/{attempt_id}/follow-up"
    assert client.get(evaluator_path, headers=evaluator_headers).status_code == 404
    owned_id = assessment_id(factory, attempt_id)
    evaluator_path = f"/api/v1/evaluator/assessments/{owned_id}/attempts/{attempt_id}/follow-up"
    assert client.get(evaluator_path, headers=candidate_headers).status_code == 200
    interview = client.get(candidate_path, headers=candidate_headers).json()
    client.put(f"{candidate_path}/questions/{interview['questions'][0]['id']}", headers=candidate_headers, json={"answer": "Discuss trade-offs."})
    assert client.post(candidate_path + "/submit", headers=candidate_headers).status_code == 200
    review_path = evaluator_path + "/review"
    reviewed = client.patch(review_path, headers=candidate_headers, json={"notes": "Private assessment note", "score": 4})
    assert reviewed.status_code == 200
    assert reviewed.json()["review_notes"] == "Private assessment note"
    candidate_view = client.get(candidate_path, headers=candidate_headers).json()
    assert candidate_view["review_notes"] is None and candidate_view["review_score"] is None
    assert candidate_view["reviewer_id"] is None and candidate_view["reviewed_at"] is None
    assert client.get(evaluator_path, headers=evaluator_headers).status_code == 404
    added = client.post(evaluator_path + "/questions", headers=candidate_headers, json={"prompt": "What alternative would you test?"})
    assert added.status_code == 200
    extra = added.json()["questions"][-1]
    assert extra["origin"] == "evaluator"
    assert extra["answer_locked"] is False
    assert client.put(f"{candidate_path}/questions/{extra['id']}", headers=candidate_headers, json={"answer": "Compare a sorting approach."}).status_code == 200
    assert client.post(candidate_path + "/submit", headers=candidate_headers).status_code == 200
    assert client.get(evaluator_path, headers=candidate_headers).json()["questions"][-1]["answer"] == "Compare a sorting approach."
    # Interview grading remains separate from the coding score.
    with factory() as session:
        interview = session.scalar(select(FollowUpInterview).where(FollowUpInterview.attempt_id == attempt_id))
        attempt = session.get(AssessmentAttempt, attempt_id)
        assert interview is not None and interview.review_score == 4
        assert attempt is not None and attempt.score == 5 and attempt.final_score is None


def test_generation_requires_ai_configuration_and_rejects_malformed_provider_output(interview_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import follow_up_interviews as api

    client, factory = interview_client
    candidate_id = uuid4()
    attempt_id = create_submitted_attempt(factory, candidate_id)
    headers = {"Authorization": f"Bearer {token(candidate_id)}"}
    url = f"/api/v1/candidate/attempts/{attempt_id}/follow-up/generate"
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    assert client.post(url, headers=headers).status_code == 503
    class MockResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(settings, "openai_api_key", "test-provider-key")
    malformed = json.dumps({"choices": [{"message": {"content": '{"questions":["one", 2, "three"]}'}}]}).encode()
    monkeypatch.setattr(api, "urlopen", lambda *_args, **_kwargs: MockResponse(malformed))
    assert client.post(url, headers=headers).status_code == 502
    monkeypatch.setattr(api, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(HTTPError("https://api.openai.com", 500, "provider error", {}, BytesIO(b"private provider detail"))))
    provider_error = client.post(url, headers=headers)
    assert provider_error.status_code == 502 and "private provider detail" not in provider_error.text
    with factory() as session:
        assert session.scalar(select(FollowUpInterview).where(FollowUpInterview.attempt_id == attempt_id)) is None


def assessment_id(factory: sessionmaker[Session], attempt_id: UUID) -> UUID:
    with factory() as session:
        return session.scalar(select(AssessmentAttempt.assessment_id).where(AssessmentAttempt.id == attempt_id))
