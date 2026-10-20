"""Persist bounded execution and score summaries for candidate attempts.

Revision ID: c2d09f8a1173
Revises: a91e8e61bc30
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c2d09f8a1173"
down_revision: Union[str, Sequence[str], None] = "a91e8e61bc30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assessment_attempts", sa.Column("execution_status", sa.String(24), server_default="not_started", nullable=False))
    op.add_column("assessment_attempts", sa.Column("score", sa.Integer(), nullable=True))
    op.add_column("assessment_attempts", sa.Column("max_score", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "attempt_execution_status_valid", "assessment_attempts",
        "execution_status IN ('not_started', 'running', 'completed', 'manual_review', 'unavailable', 'failed')",
    )
    op.add_column("attempt_responses", sa.Column("execution_status", sa.String(24), server_default="not_started", nullable=False))
    op.add_column("attempt_responses", sa.Column("score", sa.Integer(), nullable=True))
    op.add_column("attempt_responses", sa.Column("passed_test_cases", sa.Integer(), nullable=True))
    op.add_column("attempt_responses", sa.Column("total_test_cases", sa.Integer(), nullable=True))
    op.add_column("attempt_responses", sa.Column("execution_details", sa.JSON(), nullable=True))
    op.create_check_constraint(
        "response_execution_status_valid", "attempt_responses",
        "execution_status IN ('not_started', 'completed', 'compile_error', 'runtime_error', 'timeout', 'resource_limit', 'manual_review', 'unavailable', 'failed')",
    )
    op.create_check_constraint("response_score_nonnegative", "attempt_responses", "score IS NULL OR score >= 0")
    op.create_check_constraint("response_passed_cases_nonnegative", "attempt_responses", "passed_test_cases IS NULL OR passed_test_cases >= 0")
    op.create_check_constraint("response_total_cases_nonnegative", "attempt_responses", "total_test_cases IS NULL OR total_test_cases >= 0")


def downgrade() -> None:
    op.drop_constraint("response_total_cases_nonnegative", "attempt_responses", type_="check")
    op.drop_constraint("response_passed_cases_nonnegative", "attempt_responses", type_="check")
    op.drop_constraint("response_score_nonnegative", "attempt_responses", type_="check")
    op.drop_constraint("response_execution_status_valid", "attempt_responses", type_="check")
    op.drop_column("attempt_responses", "execution_details")
    op.drop_column("attempt_responses", "total_test_cases")
    op.drop_column("attempt_responses", "passed_test_cases")
    op.drop_column("attempt_responses", "score")
    op.drop_column("attempt_responses", "execution_status")
    op.drop_constraint("attempt_execution_status_valid", "assessment_attempts", type_="check")
    op.drop_column("assessment_attempts", "max_score")
    op.drop_column("assessment_attempts", "score")
    op.drop_column("assessment_attempts", "execution_status")
