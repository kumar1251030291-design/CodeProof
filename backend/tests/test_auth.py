from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import os
from uuid import UUID, uuid4

import jwt
from pypdf import PdfReader
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.core.auth import AuthenticatedIdentity
from app.core.authorization import (
    assign_verified_owner,
    get_owned_assessment,
    list_owned_assessments,
    require_evaluator,
)
from app.core.config import settings
from app.core.database import Base, get_db_session
from app.core import security
from app.core import execution
from app.models import (
    AccessCodeRateLimit,
    Assessment,
    AssessmentAccessGrant,
    AssessmentAttempt,
    AttemptResponse,
    Question,
    TestCase as CaseModel,
    UserProfile,
    UserRole,
)

TEST_URL = "https://auth-unit-test.supabase.co"
TEST_SECRET = "test-only-signing-key-do-not-reuse"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(settings, "supabase_url", TEST_URL)
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_SECRET)
    monkeypatch.setattr(settings, "supabase_jwt_audience", "authenticated")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with test_session_factory() as session:
            yield session

    main.app.dependency_overrides[get_db_session] = override_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.pop(get_db_session, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_token(
    user_id: UUID,
    *,
    expires_in: timedelta = timedelta(minutes=5),
    secret: str = TEST_SECRET,
    issuer: str = f"{TEST_URL}/auth/v1",
    audience: str = "authenticated",
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": "candidate@example.test",
        "aud": audience,
        "iss": issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_me_rejects_missing_malformed_and_expired_tokens(client: TestClient) -> None:
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401

    expired = make_token(uuid4(), expires_in=timedelta(seconds=-5))
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

    wrong_signature = make_token(uuid4(), secret="different-test-signing-key-for-unit-test")
    wrong_issuer = make_token(uuid4(), issuer="https://other-project.example/auth/v1")
    wrong_audience = make_token(uuid4(), audience="service_role")
    for token in (wrong_signature, wrong_issuer, wrong_audience):
        response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


def test_auth_health_reports_only_safe_jwks_readiness(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PublicKeyMetadata:
        algorithm_name = "ES256"

    class ReachableJwks:
        def get_signing_keys(self) -> list[PublicKeyMetadata]:
            return [PublicKeyMetadata()]

    monkeypatch.setattr(security, "_jwks_client", lambda _url: ReachableJwks())
    response = client.get("/api/v1/health/auth")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "project_url_configured": True,
        "audience_configured": True,
        "legacy_hs256_secret_configured": True,
        "jwks_reachable": True,
        "jwks_supported_algorithms": ["ES256"],
    }
    assert client.get("/health").json() == {"status": "healthy"}
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/me").status_code == 401
    preflight = client.options(
        "/api/v1/candidate/attempts/test/report.pdf",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"
    cors_response = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert cors_response.headers.get("access-control-expose-headers") == "Content-Disposition"


def test_auth_health_fails_closed_when_jwks_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnavailableJwks:
        def get_signing_keys(self) -> list[object]:
            raise security.PyJWKClientConnectionError("private transport detail")

    monkeypatch.setattr(settings, "supabase_jwt_secret", None)
    monkeypatch.setattr(security, "_jwks_client", lambda _url: UnavailableJwks())
    response = client.get("/api/v1/health/auth")

    assert response.status_code == 200
    assert response.json()["status"] == "not_ready"
    assert response.json()["jwks_reachable"] is False
    assert "private transport detail" not in response.text
    assert settings.supabase_url not in response.text


def test_me_creates_profile_with_both_roles_and_is_idempotent(client: TestClient) -> None:
    user_id = uuid4()
    headers = {"Authorization": f"Bearer {make_token(user_id)}"}
    response = client.get("/api/v1/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["profile"]["id"] == str(user_id)
    assert response.json()["roles"] == ["candidate", "evaluator"]
    assert response.json()["access_state"] == "authorized"

    repeated = client.get("/api/v1/me", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["roles"] == ["candidate", "evaluator"]

    db_generator = main.app.dependency_overrides[get_db_session]()
    session = next(db_generator)
    try:
        assert session.query(UserRole).filter_by(user_id=user_id).count() == 2
    finally:
        db_generator.close()


def test_existing_profile_is_completed_to_both_roles(client: TestClient) -> None:
    user_id = uuid4()
    db_generator = main.app.dependency_overrides[get_db_session]()
    session = next(db_generator)
    try:
        session.add(UserProfile(id=user_id))
        session.add(UserRole(user_id=user_id, role="candidate"))
        session.commit()
    finally:
        db_generator.close()

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {make_token(user_id)}"})
    assert response.status_code == 200
    assert response.json()["roles"] == ["candidate", "evaluator"]


def test_es256_token_uses_cached_jwks_verification_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid4()
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "iss": f"{TEST_URL}/auth/v1",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        private_key,
        algorithm="ES256",
        headers={"kid": "test-es256-key"},
    )

    class TestSigningKey:
        algorithm_name = "ES256"

        def __init__(self) -> None:
            self.key = public_key

    class TestJwksClient:
        def get_signing_key_from_jwt(self, _token: str) -> TestSigningKey:
            return TestSigningKey()

    monkeypatch.setattr(security, "_jwks_client", lambda _url: TestJwksClient())
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["profile"]["id"] == str(user_id)
    assert response.json()["roles"] == ["candidate", "evaluator"]
    assert response.json()["access_state"] == "authorized"


def test_evaluator_a_cannot_access_evaluator_b_assessment(client: TestClient) -> None:
    owner_a, owner_b = uuid4(), uuid4()
    db_generator = main.app.dependency_overrides[get_db_session]()
    session = next(db_generator)
    try:
        profile_a = UserProfile(id=owner_a)
        profile_b = UserProfile(id=owner_b)
        assessment = Assessment(
            id=uuid4(),
            title="Private assessment",
            description="Private instructions",
            status="draft",
            owner_id=owner_b,
        )
        own_assessment = Assessment(
            id=uuid4(),
            title="A's assessment",
            description="",
            status="draft",
            owner_id=owner_a,
        )
        session.add_all([profile_a, profile_b, assessment, own_assessment])
        session.commit()
        identity_a = AuthenticatedIdentity(profile=profile_a, email=None, roles=("candidate", "evaluator"))
        with pytest.raises(HTTPException) as denied:
            get_owned_assessment(session, assessment.id, identity_a)
        assert denied.value.status_code == 404
        assert [item.id for item in list_owned_assessments(session, identity_a)] == [own_assessment.id]
        unchanged = session.get(Assessment, assessment.id)
        assert unchanged is not None and unchanged.title == "Private assessment"
    finally:
        db_generator.close()


def test_assessment_owner_is_overwritten_from_verified_identity(client: TestClient) -> None:
    verified_id, spoofed_id = uuid4(), uuid4()
    identity = AuthenticatedIdentity(
        profile=UserProfile(id=verified_id),
        email=None,
        roles=("candidate", "evaluator"),
    )
    assessment = Assessment(
        title="New assessment",
        description="",
        status="draft",
        owner_id=spoofed_id,
    )
    assign_verified_owner(assessment, identity)
    assert assessment.owner_id == verified_id
    assert assessment.owner_id != spoofed_id


def test_evaluator_foundation_rejects_identity_without_evaluator_role() -> None:
    identity = AuthenticatedIdentity(
        profile=UserProfile(id=uuid4()),
        email=None,
        roles=("candidate",),
    )
    with pytest.raises(HTTPException) as denied:
        require_evaluator(identity)
    assert denied.value.status_code == 403


def test_authenticated_user_cannot_assign_roles_through_public_api(client: TestClient) -> None:
    user_id = uuid4()
    headers = {"Authorization": f"Bearer {make_token(user_id)}"}
    response = client.post("/api/v1/me/roles", headers=headers, json={"role": "evaluator"})

    assert response.status_code == 404
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["roles"] == ["candidate", "evaluator"]
    assert me.json()["access_state"] == "authorized"


def test_health_routes_remain_public(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _query: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    monkeypatch.setattr(main, "engine", FakeEngine())
    assert client.get("/api/v1/health/database").status_code == 200


def draft_payload(*, title: str = "API Assessment", access_mode: str = "open") -> dict[str, object]:
    return {
        "title": title,
        "description": "Assessment description",
        "instructions": "Complete each question.",
        "difficulty": "medium",
        "duration_seconds": 1800,
        "allowed_languages": ["python", "c"],
        "access_mode": access_mode,
        "purpose": "hiring",
        "questions": [
            {
                "title": "First problem",
                "prompt": "Implement a solution.",
                "question_type": "programming",
                "difficulty": "easy",
                "points": 10,
                "default_language": "python",
                "allowed_languages": ["python"],
                "display_order": 0,
                "problem_statement": "Solve the problem efficiently.",
                "examples": "Input: 1\nOutput: 1",
                "test_cases": [
                    {
                        "input_data": "1",
                        "expected_output": "1",
                        "visibility": "public",
                        "display_order": 0,
                    },
                    {
                        "input_data": "9",
                        "expected_output": "9",
                        "visibility": "hidden",
                        "display_order": 1,
                    },
                ],
            }
        ],
    }


def test_assessment_draft_crud_is_owner_scoped_and_reorders_questions(client: TestClient) -> None:
    owner_a, owner_b = uuid4(), uuid4()
    headers_a = {"Authorization": f"Bearer {make_token(owner_a)}"}
    headers_b = {"Authorization": f"Bearer {make_token(owner_b)}"}
    base = "/api/v1/evaluator/assessments"

    created = client.post(base, headers=headers_a, json=draft_payload())
    assert created.status_code == 201, created.text
    assessment = created.json()
    assessment_id = assessment["id"]
    question_id = assessment["questions"][0]["id"]
    assert assessment["status"] == "draft"
    assert assessment["questions"][0]["test_cases"][1]["visibility"] == "hidden"

    assert client.get(base, headers=headers_a).json()["assessments"][0]["id"] == assessment_id
    assert client.get(base, headers=headers_b).json()["assessments"] == []
    assert client.get(f"{base}/{assessment_id}", headers=headers_b).status_code == 404
    foreign_update = draft_payload(title="Stolen update")
    assert client.put(f"{base}/{assessment_id}", headers=headers_b, json=foreign_update).status_code == 404
    assert client.delete(f"{base}/{assessment_id}", headers=headers_b).status_code == 404

    detail = client.get(f"{base}/{assessment_id}", headers=headers_a)
    assert detail.status_code == 200
    payload = draft_payload(title="Updated API Assessment")
    payload["questions"][0]["id"] = question_id
    update = client.put(f"{base}/{assessment_id}", headers=headers_a, json=payload)
    assert update.status_code == 200, update.text
    assert update.json()["title"] == "Updated API Assessment"

    second_question = {
        "title": "Second problem",
        "prompt": "Explain this code.",
        "question_type": "explanation",
        "difficulty": "medium",
        "points": 5,
        "default_language": "python",
        "display_order": 1,
    }
    added = client.post(f"{base}/{assessment_id}/questions", headers=headers_a, json=second_question)
    assert added.status_code == 201, added.text
    second_id = added.json()["id"]
    edited = {**second_question, "title": "Edited explanation", "display_order": 1}
    assert client.put(f"{base}/{assessment_id}/questions/{second_id}", headers=headers_a, json=edited).status_code == 200

    reordered = client.put(
        f"{base}/{assessment_id}/questions/reorder",
        headers=headers_a,
        json={"question_ids": [second_id, question_id]},
    )
    assert reordered.status_code == 200, reordered.text
    assert [item["id"] for item in reordered.json()] == [second_id, question_id]
    assert reordered.json()[0]["display_order"] == 0
    assert client.delete(f"{base}/{assessment_id}/questions/{question_id}", headers=headers_a).status_code == 204
    assert len(client.get(f"{base}/{assessment_id}", headers=headers_a).json()["questions"]) == 1
    assert client.delete(f"{base}/{assessment_id}", headers=headers_a).status_code == 204
    assert client.get(f"{base}/{assessment_id}", headers=headers_a).status_code == 404


def test_assessment_rejects_spoofed_owner_and_invalid_question_data(client: TestClient) -> None:
    user_id = uuid4()
    headers = {"Authorization": f"Bearer {make_token(user_id)}"}
    base = "/api/v1/evaluator/assessments"
    spoofed = draft_payload()
    spoofed["owner_id"] = str(uuid4())
    assert client.post(base, headers=headers, json=spoofed).status_code == 422

    invalid_duration = draft_payload()
    invalid_duration["duration_seconds"] = -1
    assert client.post(base, headers=headers, json=invalid_duration).status_code == 422

    invalid_language = draft_payload()
    invalid_language["allowed_languages"] = ["rust"]
    assert client.post(base, headers=headers, json=invalid_language).status_code == 422

    invalid_points = draft_payload()
    invalid_points["questions"][0]["points"] = -5
    assert client.post(base, headers=headers, json=invalid_points).status_code == 422

    malformed_order = draft_payload()
    malformed_order["questions"] = [
        malformed_order["questions"][0],
        {**malformed_order["questions"][0], "display_order": 4},
    ]
    assert client.post(base, headers=headers, json=malformed_order).status_code == 422


def test_restricted_access_codes_are_hashed_and_returned_only_once(client: TestClient) -> None:
    user_id = uuid4()
    headers = {"Authorization": f"Bearer {make_token(user_id)}"}
    base = "/api/v1/evaluator/assessments"
    created = client.post(base, headers=headers, json=draft_payload(access_mode="restricted"))
    assert created.status_code == 201, created.text
    code = created.json()["access_code"]
    assert isinstance(code, str) and code
    assessment_id = created.json()["id"]
    assert code not in str(client.get(f"{base}/{assessment_id}", headers=headers).json())

    session_gen = main.app.dependency_overrides[get_db_session]()
    session = next(session_gen)
    try:
        stored_hash = session.get(Assessment, UUID(assessment_id)).access_code_hash
        assert stored_hash == hashlib.sha256(code.encode("utf-8")).hexdigest()
        assert stored_hash != code
    finally:
        session_gen.close()

    rotated = client.post(f"{base}/{assessment_id}/access-code", headers=headers)
    assert rotated.status_code == 200
    assert rotated.json()["access_code"] != code
    assert code not in str(client.get(f"{base}/{assessment_id}", headers=headers).json())


def test_publish_validation_publish_and_archive_are_owner_scoped(client: TestClient) -> None:
    user_a, user_b = uuid4(), uuid4()
    headers_a = {"Authorization": f"Bearer {make_token(user_a)}"}
    headers_b = {"Authorization": f"Bearer {make_token(user_b)}"}
    base = "/api/v1/evaluator/assessments"
    payload = draft_payload()
    payload["description"] = ""
    assessment = client.post(base, headers=headers_a, json=payload).json()
    assessment_id = assessment["id"]
    assert client.post(f"{base}/{assessment_id}/publish", headers=headers_b).status_code == 404
    missing_content = client.post(f"{base}/{assessment_id}/publish", headers=headers_a)
    assert missing_content.status_code == 422

    payload = draft_payload()
    payload["questions"][0]["id"] = assessment["questions"][0]["id"]
    assert client.put(f"{base}/{assessment_id}", headers=headers_a, json=payload).status_code == 200
    published = client.post(f"{base}/{assessment_id}/publish", headers=headers_a)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert client.put(f"{base}/{assessment_id}", headers=headers_a, json=payload).status_code == 409
    archived = client.post(f"{base}/{assessment_id}/archive", headers=headers_a)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_publish_rejects_coding_questions_outside_runner_case_limits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = uuid4()
    headers = {"Authorization": f"Bearer {make_token(owner_id)}"}
    base = "/api/v1/evaluator/assessments"

    empty_cases = draft_payload()
    empty_cases["questions"][0]["test_cases"] = []  # type: ignore[index]
    created = client.post(base, headers=headers, json=empty_cases)
    assert created.status_code == 201
    assessment_id = created.json()["id"]
    assert client.post(f"{base}/{assessment_id}/publish", headers=headers).status_code == 422
    assert client.get(f"{base}/{assessment_id}", headers=headers).json()["status"] == "draft"

    monkeypatch.setattr(settings, "code_runner_max_cases", 1)
    too_many_cases = draft_payload()
    too_many_cases["questions"][0]["test_cases"] = [  # type: ignore[index]
        {"input_data": str(index), "expected_output": str(index), "visibility": "hidden", "display_order": index}
        for index in range(2)
    ]
    second = client.post(base, headers=headers, json=too_many_cases)
    assert second.status_code == 201
    rejected = client.post(f"{base}/{second.json()['id']}/publish", headers=headers)
    assert rejected.status_code == 422
    assert "test cases" in rejected.json()["detail"]


def test_candidate_api_is_not_exposed_and_hidden_case_data_is_evaluator_only(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    detail = client.post("/api/v1/evaluator/assessments", headers=headers, json=draft_payload()).json()
    assessment_id = detail["id"]
    assert client.get(f"/api/v1/candidate/assessments/{assessment_id}", headers=headers).status_code == 404
    evaluator_view = client.get(f"/api/v1/evaluator/assessments/{assessment_id}", headers=headers)
    assert evaluator_view.status_code == 200
    assert any(case["visibility"] == "hidden" for case in evaluator_view.json()["questions"][0]["test_cases"])


def test_assessment_routes_require_verified_bearer_authentication(client: TestClient) -> None:
    base = "/api/v1/evaluator/assessments"
    assert client.get(base).status_code == 401
    assert client.post(base, json=draft_payload()).status_code == 401
    assert client.get("/api/v1/candidate/assessments").status_code == 401
    assert client.post("/api/v1/candidate/assessments/access-code", json={"access_code": "code"}).status_code == 401
    assert client.get("/health").status_code == 200


def _publish_assessment(
    client: TestClient,
    owner_id: UUID,
    *,
    access_mode: str = "open",
    max_attempts: int | None = None,
    duration_seconds: int = 1800,
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {make_token(owner_id)}"}
    payload = draft_payload(access_mode=access_mode)
    payload["max_attempts"] = max_attempts
    payload["duration_seconds"] = duration_seconds
    created = client.post("/api/v1/evaluator/assessments", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    record = created.json()
    payload["questions"][0]["id"] = record["questions"][0]["id"]  # type: ignore[index]
    updated = client.put(f"/api/v1/evaluator/assessments/{record['id']}", headers=headers, json=payload)
    assert updated.status_code == 200, updated.text
    published = client.post(f"/api/v1/evaluator/assessments/{record['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    return {**published.json(), "access_code": record.get("access_code")}


def test_candidate_discovery_and_detail_exclude_private_question_data(client: TestClient) -> None:
    published = _publish_assessment(client, uuid4())
    headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    listed = client.get("/api/v1/candidate/assessments", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == published["id"] for item in listed.json()["assessments"])

    detail = client.get(f"/api/v1/candidate/assessments/{published['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert "owner_id" not in body and "access_code_hash" not in body
    question = body["questions"][0]
    assert question["points"] == 10
    assert len(question["public_examples"]) == 1
    assert question["public_examples"][0]["expected_output"] == "1"
    assert "test_cases" not in question
    assert "correct_answer" not in question
    assert "hidden" not in str(body)

    draft = client.post(
        "/api/v1/evaluator/assessments",
        headers={"Authorization": f"Bearer {make_token(uuid4())}"},
        json=draft_payload(),
    ).json()
    after_draft = client.get("/api/v1/candidate/assessments", headers=headers)
    assert all(item["id"] != draft["id"] for item in after_draft.json()["assessments"])
    assert client.get(f"/api/v1/candidate/assessments/{draft['id']}", headers=headers).status_code == 404


def test_restricted_assessment_requires_grant_and_code_checks_are_throttled(client: TestClient) -> None:
    owner_id = uuid4()
    published = _publish_assessment(client, owner_id, access_mode="restricted")
    assessment_id = published["id"]
    code = published["access_code"]
    candidate_id = uuid4()
    headers = {"Authorization": f"Bearer {make_token(candidate_id)}"}
    assert all(item["id"] != assessment_id for item in client.get("/api/v1/candidate/assessments", headers=headers).json()["assessments"])
    assert client.get(f"/api/v1/candidate/assessments/{assessment_id}", headers=headers).status_code == 404

    wrong = client.post("/api/v1/candidate/assessments/access-code", headers=headers, json={"access_code": "wrong"})
    assert wrong.status_code == 404
    assert wrong.json()["detail"] == "Access code invalid or assessment unavailable"
    verified = client.post("/api/v1/candidate/assessments/access-code", headers=headers, json={"access_code": code})
    assert verified.status_code == 200, verified.text
    assert verified.json()["assessment"]["id"] == assessment_id
    assert client.get(f"/api/v1/candidate/assessments/{assessment_id}", headers=headers).status_code == 200

    owner_headers = {"Authorization": f"Bearer {make_token(owner_id)}"}
    rotated = client.post(f"/api/v1/evaluator/assessments/{assessment_id}/access-code", headers=owner_headers)
    assert rotated.status_code == 200
    assert rotated.json()["access_code"] != code
    assert client.get(f"/api/v1/candidate/assessments/{assessment_id}", headers=headers).status_code == 404

    stranger_headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    assert client.get(f"/api/v1/candidate/assessments/{assessment_id}", headers=stranger_headers).status_code == 404

    limited_headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    for _ in range(5):
        result = client.post("/api/v1/candidate/assessments/access-code", headers=limited_headers, json={"access_code": "bad"})
        assert result.status_code == 404
    limited = client.post("/api/v1/candidate/assessments/access-code", headers=limited_headers, json={"access_code": "bad"})
    assert limited.status_code == 429


def test_candidate_attempt_resume_limit_deadline_and_submission_privacy(client: TestClient) -> None:
    published = _publish_assessment(client, uuid4(), max_attempts=1, duration_seconds=60)
    assessment_id = published["id"]
    candidate_id = uuid4()
    headers = {"Authorization": f"Bearer {make_token(candidate_id)}"}
    started = client.post(f"/api/v1/candidate/assessments/{assessment_id}/attempts", headers=headers)
    assert started.status_code == 200, started.text
    attempt = started.json()
    resumed = client.post(f"/api/v1/candidate/assessments/{assessment_id}/attempts", headers=headers)
    assert resumed.json()["id"] == attempt["id"]

    question_id = published["questions"][0]["id"]
    saved = client.put(
        f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}",
        headers=headers,
        json={"response_text": "candidate code", "programming_language": "python"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["response_text"] == "candidate code"
    assert "candidate_id" not in saved.json() and saved.json()["score"] is None

    stranger_headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    assert client.get(f"/api/v1/candidate/attempts/{attempt['id']}", headers=stranger_headers).status_code == 404
    assert client.put(
        f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}",
        headers=stranger_headers,
        json={"response_text": "stolen", "programming_language": "python"},
    ).status_code == 404
    assert client.put(
        f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}",
        headers=headers,
        json={"response_text": "x", "programming_language": "python", "candidate_id": str(stranger_headers)},
    ).status_code == 422

    submitted = client.post(f"/api/v1/candidate/attempts/{attempt['id']}/submit", headers=headers)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["execution_status"] == "unavailable"
    assert submitted.json()["score"] is None
    assert client.post(f"/api/v1/candidate/assessments/{assessment_id}/attempts", headers=headers).status_code == 409


def test_candidate_deadline_is_enforced_server_side(client: TestClient) -> None:
    published = _publish_assessment(client, uuid4())
    headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    attempt = client.post(f"/api/v1/candidate/assessments/{published['id']}/attempts", headers=headers).json()
    override = main.app.dependency_overrides[get_db_session]()
    session = next(override)
    try:
        saved_attempt = session.get(AssessmentAttempt, UUID(attempt["id"]))
        assert saved_attempt is not None
        saved_attempt.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    finally:
        override.close()
    result = client.post(f"/api/v1/candidate/attempts/{attempt['id']}/submit", headers=headers)
    assert result.status_code == 409
    own_attempt = client.get(f"/api/v1/candidate/attempts/{attempt['id']}", headers=headers)
    assert own_attempt.json()["status"] == "expired"


def test_submit_scores_server_side_and_results_are_owner_scoped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id = uuid4()
    published = _publish_assessment(client, owner_id)
    session_generator = main.app.dependency_overrides[get_db_session]()
    session = next(session_generator)
    try:
        assessment = session.get(Assessment, UUID(str(published["id"])))
        assert assessment is not None
        assessment.show_results_after_submission = True
        session.commit()
    finally:
        session_generator.close()

    observed: list[list[tuple[str, str]]] = []

    def fake_run_question(language: str, source: str, cases: list[tuple[str, str]]) -> tuple[list[dict[str, object]], int]:
        assert language == "python"
        assert source == "candidate code"
        observed.append(cases)
        return ([{"case_order": i, "status": "completed", "passed": True} for i in range(len(cases))], len(cases))

    monkeypatch.setattr(settings, "code_execution_enabled", True)
    monkeypatch.setattr(execution, "run_question", fake_run_question)
    headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    attempt = client.post(f"/api/v1/candidate/assessments/{published['id']}/attempts", headers=headers).json()
    question_id = published["questions"][0]["id"]  # type: ignore[index]
    saved = client.put(
        f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}",
        headers=headers,
        json={"response_text": "candidate code", "programming_language": "python", "score": 100000},
    )
    assert saved.status_code == 422  # Candidate input cannot supply a score.
    assert client.put(
        f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}",
        headers=headers,
        json={"response_text": "candidate code", "programming_language": "python"},
    ).status_code == 200
    submitted = client.post(f"/api/v1/candidate/attempts/{attempt['id']}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["execution_status"] == "completed"
    assert body["score"] == 10 and body["max_score"] == 10
    assert len(observed[0]) == 2  # Includes hidden cases; inputs and expected values aren't returned.
    assert "execution_details" not in str(body)
    assert "expected_output" not in str(body)

    owner_headers = {"Authorization": f"Bearer {make_token(owner_id)}"}
    assert client.get(f"/api/v1/evaluator/assessments/{published['id']}/results", headers=owner_headers).status_code == 200
    stranger_headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    assert client.get(f"/api/v1/evaluator/assessments/{published['id']}/results", headers=stranger_headers).status_code == 404


@pytest.mark.skipif(
    os.getenv("CODEPROOF_RUNNER_INTEGRATION") != "1",
    reason="Set CODEPROOF_RUNNER_INTEGRATION=1 to run the API-to-Docker submission check",
)
def test_candidate_submission_scores_through_real_docker_runner(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id, candidate_id = uuid4(), uuid4()
    published = _publish_assessment(client, owner_id)
    monkeypatch.setattr(settings, "code_execution_enabled", True)
    candidate_headers = {"Authorization": f"Bearer {make_token(candidate_id)}"}
    attempt = client.post(
        f"/api/v1/candidate/assessments/{published['id']}/attempts", headers=candidate_headers,
    ).json()
    question_id = published["questions"][0]["id"]  # type: ignore[index]
    saved = client.put(
        f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}",
        headers=candidate_headers,
        json={"response_text": "import sys\nprint(sys.stdin.read().strip())", "programming_language": "python"},
    )
    assert saved.status_code == 200
    submitted = client.post(f"/api/v1/candidate/attempts/{attempt['id']}/submit", headers=candidate_headers)
    assert submitted.status_code == 200, submitted.text
    # Candidate result visibility is disabled in this assessment; only the owner sees the score.
    assert submitted.json()["execution_status"] == "completed"
    assert submitted.json()["score"] is None
    evaluator_headers = {"Authorization": f"Bearer {make_token(owner_id)}"}
    results = client.get(f"/api/v1/evaluator/assessments/{published['id']}/results", headers=evaluator_headers)
    assert results.status_code == 200
    result = results.json()["attempts"][0]
    assert result["score"] == 10 and result["final_score"] == 10


def _extract_pdf_text(response: object) -> str:
    content = response.content  # type: ignore[attr-defined]
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert response.headers["content-type"].startswith("application/pdf")  # type: ignore[attr-defined]
    assert response.headers["content-disposition"].startswith("attachment; filename=\"codeproof-")  # type: ignore[attr-defined]
    assert content.startswith(b"%PDF-") and content.rstrip().endswith(b"%%EOF")
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)


def test_candidate_and_evaluator_pdf_exports_enforce_scope_and_result_visibility(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id, candidate_id = uuid4(), uuid4()
    owner_headers = {"Authorization": f"Bearer {make_token(owner_id)}"}
    candidate_headers = {"Authorization": f"Bearer {make_token(candidate_id)}"}
    published = _publish_assessment(client, owner_id)
    assessment_id = str(published["id"])
    question_id = str(published["questions"][0]["id"])  # type: ignore[index]
    db_generator = main.app.dependency_overrides[get_db_session]()
    session = next(db_generator)
    try:
        assessment = session.get(Assessment, UUID(assessment_id))
        assert assessment is not None
        assessment.show_results_after_submission = True
        hidden_case = session.query(CaseModel).filter_by(question_id=UUID(question_id), visibility="hidden").one()
        hidden_case.input_data = "HIDDEN_INPUT_SHOULD_NOT_EXPORT"
        hidden_case.expected_output = "HIDDEN_OUTPUT_SHOULD_NOT_EXPORT"
        session.commit()
    finally:
        db_generator.close()

    monkeypatch.setattr(settings, "code_execution_enabled", True)
    monkeypatch.setattr(
        execution, "run_question",
        lambda _language, _source, cases: ([{"status": "completed", "passed": True} for _ in cases], len(cases)),
    )
    attempt = client.post(f"/api/v1/candidate/assessments/{assessment_id}/attempts", headers=candidate_headers).json()
    saved = client.put(
        f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}", headers=candidate_headers,
        json={"response_text": "def solution(): return 1", "programming_language": "python"},
    )
    assert saved.status_code == 200
    assert client.post(f"/api/v1/candidate/attempts/{attempt['id']}/submit", headers=candidate_headers).status_code == 200

    candidate_report_path = f"/api/v1/candidate/attempts/{attempt['id']}/report.pdf"
    candidate_response = client.get(candidate_report_path, headers=candidate_headers)
    candidate_text = _extract_pdf_text(candidate_response)
    assert "Final score" in candidate_text and "10 / 10" in candidate_text
    assert "Question-level automatic results" in candidate_text
    assert "HIDDEN_INPUT_SHOULD_NOT_EXPORT" not in candidate_text
    assert "HIDDEN_OUTPUT_SHOULD_NOT_EXPORT" not in candidate_text
    assert "def solution" not in candidate_text
    assert client.get(candidate_report_path, headers={"Authorization": f"Bearer {make_token(uuid4())}"}).status_code == 404
    in_progress = client.post(f"/api/v1/candidate/assessments/{assessment_id}/attempts", headers=candidate_headers)
    assert in_progress.status_code == 200
    in_progress_text = _extract_pdf_text(client.get(
        f"/api/v1/candidate/attempts/{in_progress.json()['id']}/report.pdf", headers=candidate_headers,
    ))
    assert "still in progress" in in_progress_text and "Final score" not in in_progress_text

    # The PDF uses the same result-visibility helper as the candidate API.
    db_generator = main.app.dependency_overrides[get_db_session]()
    session = next(db_generator)
    try:
        assessment = session.get(Assessment, UUID(assessment_id))
        assert assessment is not None
        assessment.show_results_after_submission = False
        session.commit()
    finally:
        db_generator.close()
    hidden_result_text = _extract_pdf_text(client.get(candidate_report_path, headers=candidate_headers))
    assert "Results are not yet available" in hidden_result_text
    assert "Final score" not in hidden_result_text
    assert "Question-level automatic results" not in hidden_result_text

    evaluator_path = f"/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt['id']}/report.pdf"
    evaluator_text = _extract_pdf_text(client.get(evaluator_path, headers=owner_headers))
    assert "Candidate answer" in evaluator_text and "def solution(): return 1" in evaluator_text
    assert "HIDDEN_INPUT_SHOULD_NOT_EXPORT" not in evaluator_text
    assert "HIDDEN_OUTPUT_SHOULD_NOT_EXPORT" not in evaluator_text
    assert client.get(evaluator_path, headers={"Authorization": f"Bearer {make_token(uuid4())}"}).status_code == 404

    foreign = _publish_assessment(client, uuid4())
    foreign_attempt = client.post(
        f"/api/v1/candidate/assessments/{foreign['id']}/attempts", headers=candidate_headers,
    )
    assert foreign_attempt.status_code == 200
    assert client.get(
        f"/api/v1/evaluator/assessments/{assessment_id}/attempts/{foreign_attempt.json()['id']}/report.pdf",
        headers=owner_headers,
    ).status_code == 404


def test_manual_question_reviews_are_owner_scoped_and_finalize_server_scores(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_id, candidate_id = uuid4(), uuid4()
    owner_headers = {"Authorization": f"Bearer {make_token(owner_id)}"}
    candidate_headers = {"Authorization": f"Bearer {make_token(candidate_id)}"}
    payload = draft_payload(title="Written review assessment")
    payload["show_results_after_submission"] = True
    questions = payload["questions"]
    assert isinstance(questions, list)
    questions[0]["points"] = 10
    for order in (1, 2):
        questions.append({
            "title": f"Written response {order}", "prompt": "Explain your reasoning.",
            "question_type": "explanation", "difficulty": "medium", "points": 5,
            "default_language": "python", "allowed_languages": [], "display_order": order,
            "problem_statement": "Explain your approach.", "examples": "", "test_cases": [],
        })
    created = client.post("/api/v1/evaluator/assessments", headers=owner_headers, json=payload)
    assert created.status_code == 201, created.text
    assessment = created.json()
    assessment_id = assessment["id"]
    for index, question in enumerate(assessment["questions"]):
        payload["questions"][index]["id"] = question["id"]  # type: ignore[index]
    assert client.put(f"/api/v1/evaluator/assessments/{assessment_id}", headers=owner_headers, json=payload).status_code == 200
    assert client.post(f"/api/v1/evaluator/assessments/{assessment_id}/publish", headers=owner_headers).status_code == 200
    foreign_assessment = _publish_assessment(client, uuid4())

    monkeypatch.setattr(settings, "code_execution_enabled", True)
    monkeypatch.setattr(
        execution, "run_question",
        lambda _language, _source, cases: ([{"status": "completed", "passed": True} for _ in cases], len(cases)),
    )
    attempt = client.post(f"/api/v1/candidate/assessments/{assessment_id}/attempts", headers=candidate_headers).json()
    question_ids = [question["id"] for question in assessment["questions"]]
    assert client.put(f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_ids[0]}", headers=candidate_headers,
                      json={"response_text": "candidate code", "programming_language": "python"}).status_code == 200
    for question_id in question_ids[1:]:
        assert client.put(f"/api/v1/candidate/attempts/{attempt['id']}/responses/{question_id}", headers=candidate_headers,
                          json={"response_text": "Reasoned answer", "programming_language": None}).status_code == 200
    submitted = client.post(f"/api/v1/candidate/attempts/{attempt['id']}/submit", headers=candidate_headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["score"] is None  # Hidden until every written answer is reviewed.

    results_path = f"/api/v1/evaluator/assessments/{assessment_id}/results"
    results = client.get(results_path, headers=owner_headers)
    assert results.status_code == 200, results.text
    result_attempt = results.json()["attempts"][0]
    assert result_attempt["score"] == 10 and result_attempt["final_score"] is None
    assert result_attempt["review_status"] == "pending"
    written_id, other_written_id = question_ids[1:]
    review_path = f"/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt['id']}/questions/{written_id}/review"
    assert client.patch(review_path, headers=owner_headers, json={"score": 6, "feedback": "Too many points"}).status_code == 422
    assert client.patch(review_path, headers=owner_headers, json={"score": 3, "feedback": "Clear <b>explanation</b>."}).status_code == 200
    partial = client.get(results_path, headers=owner_headers).json()["attempts"][0]
    assert partial["manual_score"] == 3 and partial["final_score"] is None
    assert partial["review_status"] == "pending"
    evaluator_report_path = f"/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt['id']}/report.pdf"
    pending_evaluator_text = _extract_pdf_text(client.get(evaluator_report_path, headers=owner_headers))
    assert "Pending manual review" in pending_evaluator_text and "Awaiting manual review" in pending_evaluator_text
    pending_candidate_text = _extract_pdf_text(client.get(
        f"/api/v1/candidate/attempts/{attempt['id']}/report.pdf", headers=candidate_headers,
    ))
    assert "pending manual review" in pending_candidate_text.lower()
    assert "Final score" not in pending_candidate_text and "Question-level" not in pending_candidate_text

    candidate_view = client.get(f"/api/v1/candidate/attempts/{attempt['id']}", headers=candidate_headers).json()
    assert candidate_view["score"] is None
    assert "manual_feedback" not in str(candidate_view) and "reviewer_id" not in str(candidate_view)
    assert client.patch(review_path, headers={"Authorization": f"Bearer {make_token(uuid4())}"},
                        json={"score": 2}).status_code == 404
    foreign_question_id = foreign_assessment["questions"][0]["id"]  # type: ignore[index]
    assert client.patch(
        f"/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt['id']}/questions/{foreign_question_id}/review",
        headers=owner_headers, json={"score": 2},
    ).status_code == 404
    assert client.patch(f"{results_path.rsplit('/results', 1)[0]}/attempts/{attempt['id']}/questions/{question_ids[0]}/review",
                        headers=owner_headers, json={"score": 2}).status_code == 409

    second_path = f"/api/v1/evaluator/assessments/{assessment_id}/attempts/{attempt['id']}/questions/{other_written_id}/review"
    final_response = client.patch(second_path, headers=owner_headers, json={"score": 4, "feedback": "Good work."})
    assert final_response.status_code == 200, final_response.text
    assert final_response.json()["manual_score"] == 7
    assert final_response.json()["final_score"] == 17
    assert final_response.json()["score"] == 10  # Automatic score remains separately stored.
    assert final_response.json()["review_status"] == "complete"
    db_generator = main.app.dependency_overrides[get_db_session]()
    db_session = next(db_generator)
    try:
        saved_review = db_session.query(AttemptResponse).filter_by(attempt_id=UUID(attempt["id"]), question_id=UUID(written_id)).one()
        assert saved_review.manual_score == 3
        assert saved_review.manual_feedback == "Clear <b>explanation</b>."
        assert saved_review.reviewer_id == owner_id and saved_review.reviewed_at is not None
    finally:
        db_generator.close()
    visible = client.get(f"/api/v1/candidate/attempts/{attempt['id']}", headers=candidate_headers).json()
    assert visible["score"] == 17
    assert "manual_feedback" not in str(visible) and "reviewer_id" not in str(visible)
    final_evaluator_text = _extract_pdf_text(client.get(evaluator_report_path, headers=owner_headers))
    assert "17 / 20" in final_evaluator_text
    assert "Clear <b>explanation</b>." in final_evaluator_text
    final_candidate_text = _extract_pdf_text(client.get(
        f"/api/v1/candidate/attempts/{attempt['id']}/report.pdf", headers=candidate_headers,
    ))
    assert "17 / 20" in final_candidate_text
    assert "Clear" not in final_candidate_text and "reviewer" not in final_candidate_text.lower()


def test_candidate_discovery_respects_future_availability(client: TestClient) -> None:
    owner_headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    payload = draft_payload()
    payload["starts_at"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    created = client.post("/api/v1/evaluator/assessments", headers=owner_headers, json=payload)
    assert created.status_code == 201
    payload["questions"][0]["id"] = created.json()["questions"][0]["id"]  # type: ignore[index]
    assert client.put(f"/api/v1/evaluator/assessments/{created.json()['id']}", headers=owner_headers, json=payload).status_code == 200
    assert client.post(f"/api/v1/evaluator/assessments/{created.json()['id']}/publish", headers=owner_headers).status_code == 200
    candidate_headers = {"Authorization": f"Bearer {make_token(uuid4())}"}
    listing = client.get("/api/v1/candidate/assessments", headers=candidate_headers)
    assert all(item["id"] != created.json()["id"] for item in listing.json()["assessments"])
    assert client.post(f"/api/v1/candidate/assessments/{created.json()['id']}/attempts", headers=candidate_headers).status_code == 404
