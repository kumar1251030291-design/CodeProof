"""Request authentication and database-backed application identity."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db_session
from app.core.security import (
    AuthenticationConfigurationError,
    InvalidAccessToken,
    SigningKeyUnavailable,
    verify_supabase_access_token,
)
from app.models import UserProfile, UserRole

bearer_scheme = HTTPBearer(auto_error=False)
DEFAULT_USER_ROLES = ("candidate",)


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Verified user claims plus database-backed profile and assigned roles."""

    profile: UserProfile
    email: str | None
    roles: tuple[str, ...]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_verified_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """Verify the bearer token before any database dependency is resolved."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        claims: dict[str, Any] = verify_supabase_access_token(credentials.credentials)
    except AuthenticationConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication verification is not configured",
        ) from None
    except SigningKeyUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication signing keys are temporarily unavailable",
        ) from None
    except InvalidAccessToken:
        raise _unauthorized() from None

    return claims


def get_current_identity(
    claims: dict[str, Any] = Depends(get_verified_claims),
    session: Session = Depends(get_db_session),
) -> AuthenticatedIdentity:
    """Safely load or create the verified token subject's UUID profile."""

    sub = claims.get("sub")
    try:
        user_id = UUID(sub)
    except (TypeError, ValueError, AttributeError):
        raise _unauthorized() from None

    try:
        profile = session.get(UserProfile, user_id)
        if profile is None:
            # A savepoint lets a concurrent request win the unique UUID insert
            # without leaving this session's outer transaction unusable.
            try:
                with session.begin_nested():
                    session.add(UserProfile(id=user_id))
                    session.flush()
            except IntegrityError:
                pass
            profile = session.get(UserProfile, user_id)
        if profile is None:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="User profile is unavailable",
            )
        # Candidate is the least-privilege default. Evaluator access is granted
        # only to IDs explicitly provisioned by backend configuration.
        roles_to_grant = DEFAULT_USER_ROLES + (("evaluator",) if user_id in settings.evaluator_user_ids else ())
        for role in roles_to_grant:
            if session.get(UserRole, (user_id, role)) is not None:
                continue
            try:
                with session.begin_nested():
                    session.add(UserRole(user_id=user_id, role=role))
                    session.flush()
            except IntegrityError:
                # A concurrent request may have inserted this exact role.
                if session.get(UserRole, (user_id, role)) is None:
                    raise
        session.commit()
        stored_roles = session.scalars(select(UserRole.role).where(UserRole.user_id == user_id)).all()
        # Older migrations backfilled evaluator for every user. Keep those rows
        # untouched, but do not treat them as authority unless allowlisted.
        roles = tuple(
            role for role in stored_roles
            if role != "evaluator" or user_id in settings.evaluator_user_ids
        )
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile storage is unavailable. Check the backend database target and apply the reviewed Alembic migrations to that database.",
        ) from None

    email = claims.get("email")
    return AuthenticatedIdentity(
        profile=profile,
        email=email if isinstance(email, str) else None,
        roles=roles,
    )
