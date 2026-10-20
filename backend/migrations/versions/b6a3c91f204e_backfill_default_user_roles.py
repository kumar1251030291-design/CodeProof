"""Backfill candidate and evaluator roles for all existing profiles.

Revision ID: b6a3c91f204e
Revises: 07da4b93c1a5
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6a3c91f204e"
down_revision: Union[str, Sequence[str], None] = "07da4b93c1a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Grant both default roles to existing profiles, without duplicate rows."""
    op.execute(
        sa.text(
            """
            INSERT INTO user_roles (user_id, role)
            SELECT id, 'candidate' FROM user_profiles
            UNION ALL
            SELECT id, 'evaluator' FROM user_profiles
            ON CONFLICT (user_id, role) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """Retain assigned roles because pre-existing and backfilled rows are indistinguishable."""
