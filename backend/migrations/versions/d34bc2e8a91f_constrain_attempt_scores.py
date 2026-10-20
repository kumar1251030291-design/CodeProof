"""Constrain persisted execution scores.

Revision ID: d34bc2e8a91f
Revises: c2d09f8a1173
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d34bc2e8a91f"
down_revision: Union[str, Sequence[str], None] = "c2d09f8a1173"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("attempt_score_nonnegative", "assessment_attempts", "score IS NULL OR score >= 0")
    op.create_check_constraint("attempt_max_score_nonnegative", "assessment_attempts", "max_score IS NULL OR max_score >= 0")
    op.create_check_constraint("attempt_score_not_above_max", "assessment_attempts", "score IS NULL OR max_score IS NOT NULL AND score <= max_score")


def downgrade() -> None:
    op.drop_constraint("attempt_score_not_above_max", "assessment_attempts", type_="check")
    op.drop_constraint("attempt_max_score_nonnegative", "assessment_attempts", type_="check")
    op.drop_constraint("attempt_score_nonnegative", "assessment_attempts", type_="check")
