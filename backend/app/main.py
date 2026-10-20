"""FastAPI application entry point for CodeProof."""

from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.assessments import router as assessments_router
from app.api.ai_generation import router as ai_generation_router
from app.api.candidate_assessments import router as candidate_assessments_router
from app.api.candidate_ai import router as candidate_ai_router
from app.core.config import settings
from app.core.database import engine
from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.security import authentication_diagnostic

app = FastAPI(
    title="CodeProof API",
    version=settings.api_version,
    description="The API foundation for the CodeProof coding assessment platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],
)

app.include_router(assessments_router)
app.include_router(candidate_assessments_router)
app.include_router(candidate_ai_router)
app.include_router(ai_generation_router)


class UserProfileResponse(BaseModel):
    id: UUID
    display_name: str | None
    email: str | None


class CurrentUserResponse(BaseModel):
    profile: UserProfileResponse
    roles: list[Literal["candidate", "evaluator"]]
    access_state: Literal["authorized", "pending_access"]


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Return the basic API health status."""
    return {"status": "healthy"}


@app.get("/api/v1/health", tags=["health"])
async def versioned_health() -> dict[str, str]:
    """Return health status and the active API version."""
    return {"status": "healthy", "version": settings.api_version}


@app.get("/api/v1/health/database", tags=["health"])
def database_health() -> dict[str, str]:
    """Check database connectivity without returning internal error details."""
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not configured",
        )

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database connection is unavailable",
        ) from None

    return {"status": "healthy", "database": "connected"}


@app.get("/api/v1/health/auth", tags=["health"])
def authentication_health() -> dict[str, object]:
    """Report safe auth configuration/key readiness without accepting tokens."""
    return authentication_diagnostic()


@app.get("/api/v1/me", response_model=CurrentUserResponse, tags=["authentication"])
def current_user(
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> CurrentUserResponse:
    """Return the verified user's profile and trusted database role assignments."""
    roles = sorted(identity.roles)
    return CurrentUserResponse(
        profile=UserProfileResponse(
            id=identity.profile.id,
            display_name=identity.profile.display_name,
            email=identity.email,
        ),
        roles=roles,
        access_state="authorized" if roles else "pending_access",
    )
