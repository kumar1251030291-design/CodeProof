"""add assessment configuration checks

Revision ID: 07da4b93c1a5
Revises: 2a386e0fd130
Create Date: 2026-10-20 19:07:25.006739

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07da4b93c1a5'
down_revision: Union[str, Sequence[str], None] = '2a386e0fd130'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        "difficulty_valid",
        "assessments",
        "difficulty IN ('easy', 'medium', 'hard')",
    )
    op.create_check_constraint(
        "access_mode_valid",
        "assessments",
        "access_mode IN ('restricted', 'public')",
    )
    op.create_check_constraint(
        "purpose_valid",
        "assessments",
        "purpose IS NULL OR purpose IN ('hiring', 'practice')",
    )
    op.create_check_constraint(
        "duration_positive",
        "assessments",
        "duration_seconds > 0",
    )
    op.create_check_constraint(
        "max_attempts_positive",
        "assessments",
        "max_attempts IS NULL OR max_attempts > 0",
    )
    op.create_check_constraint(
        "availability_range_valid",
        "assessments",
        "starts_at IS NULL OR ends_at IS NULL OR starts_at < ends_at",
    )
    op.create_check_constraint(
        "access_code_hash_not_empty",
        "assessments",
        "access_code_hash IS NULL OR length(trim(access_code_hash)) > 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("access_code_hash_not_empty", "assessments", type_="check")
    op.drop_constraint("availability_range_valid", "assessments", type_="check")
    op.drop_constraint("max_attempts_positive", "assessments", type_="check")
    op.drop_constraint("duration_positive", "assessments", type_="check")
    op.drop_constraint("purpose_valid", "assessments", type_="check")
    op.drop_constraint("access_mode_valid", "assessments", type_="check")
    op.drop_constraint("difficulty_valid", "assessments", type_="check")
