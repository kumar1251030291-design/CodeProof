"""Reusable assessment ownership checks for future assessment routes."""

from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedIdentity
from app.models import Assessment


def require_evaluator(identity: AuthenticatedIdentity) -> None:
    """Require the evaluator role granted by trusted backend provisioning."""
    if "evaluator" not in identity.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Evaluator access required")


def require_candidate(identity: AuthenticatedIdentity) -> None:
    """Require the candidate role granted by trusted backend provisioning."""
    if "candidate" not in identity.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Candidate access required")


def assign_verified_owner(
    assessment: Assessment,
    identity: AuthenticatedIdentity,
) -> Assessment:
    """Set the creator from the verified identity, overriding any payload value."""
    require_evaluator(identity)
    assessment.owner_id = identity.profile.id
    return assessment


def get_owned_assessment(
    session: Session,
    assessment_id: UUID,
    identity: AuthenticatedIdentity,
) -> Assessment:
    """Return only an assessment owned by the verified evaluator.

    The owner predicate is part of the database query. Missing and other-owner
    IDs share a 404 response so private assessment existence is not disclosed.
    """
    require_evaluator(identity)
    assessment = session.scalar(
        select(Assessment).where(
            Assessment.id == assessment_id,
            Assessment.owner_id == identity.profile.id,
        )
    )
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def list_owned_assessments(
    session: Session,
    identity: AuthenticatedIdentity,
) -> Sequence[Assessment]:
    """List only assessments whose owner is the verified evaluator profile."""
    require_evaluator(identity)
    return session.scalars(
        select(Assessment)
        .where(Assessment.owner_id == identity.profile.id)
        .order_by(Assessment.created_at.desc())
    ).all()
