"""Add question-level manual grading and final score state.

Revision ID: f1a2b3c4d5e6
Revises: d34bc2e8a91f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d34bc2e8a91f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assessment_attempts", sa.Column("manual_score", sa.Integer(), nullable=True))
    op.add_column("assessment_attempts", sa.Column("final_score", sa.Integer(), nullable=True))
    op.add_column(
        "assessment_attempts",
        sa.Column("review_status", sa.String(length=20), server_default="not_required", nullable=False),
    )
    op.add_column("attempt_responses", sa.Column("manual_score", sa.Integer(), nullable=True))
    op.add_column("attempt_responses", sa.Column("manual_feedback", sa.Text(), nullable=True))
    op.add_column("attempt_responses", sa.Column("reviewer_id", sa.Uuid(), nullable=True))
    op.add_column("attempt_responses", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_response_reviewer", "attempt_responses", "user_profiles", ["reviewer_id"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        "attempt_manual_score_nonnegative", "assessment_attempts", "manual_score IS NULL OR manual_score >= 0"
    )
    op.create_check_constraint(
        "attempt_final_score_nonnegative", "assessment_attempts", "final_score IS NULL OR final_score >= 0"
    )
    op.create_check_constraint(
        "attempt_final_score_not_above_max", "assessment_attempts",
        "final_score IS NULL OR max_score IS NOT NULL AND final_score <= max_score",
    )
    op.create_check_constraint(
        "attempt_review_status_valid", "assessment_attempts",
        "review_status IN ('pending', 'complete', 'not_required')",
    )
    op.create_check_constraint(
        "response_manual_score_nonnegative", "attempt_responses", "manual_score IS NULL OR manual_score >= 0"
    )

    # Preserve historical automatic scores and mark old written answers for review.
    op.execute("UPDATE assessment_attempts SET final_score = score, manual_score = 0 WHERE execution_status = 'completed' AND score IS NOT NULL")
    op.execute("""
        UPDATE assessment_attempts AS attempt
        SET review_status = 'pending'
        WHERE EXISTS (
            SELECT 1 FROM attempt_responses AS response
            JOIN questions AS question ON question.id = response.question_id
            WHERE response.attempt_id = attempt.id
              AND question.question_type = 'explanation'
              AND response.execution_status = 'manual_review'
        )
    """)


def downgrade() -> None:
    op.drop_constraint("response_manual_score_nonnegative", "attempt_responses", type_="check")
    op.drop_constraint("attempt_review_status_valid", "assessment_attempts", type_="check")
    op.drop_constraint("attempt_final_score_not_above_max", "assessment_attempts", type_="check")
    op.drop_constraint("attempt_final_score_nonnegative", "assessment_attempts", type_="check")
    op.drop_constraint("attempt_manual_score_nonnegative", "assessment_attempts", type_="check")
    op.drop_constraint("fk_response_reviewer", "attempt_responses", type_="foreignkey")
    op.drop_column("attempt_responses", "reviewed_at")
    op.drop_column("attempt_responses", "reviewer_id")
    op.drop_column("attempt_responses", "manual_feedback")
    op.drop_column("attempt_responses", "manual_score")
    op.drop_column("assessment_attempts", "review_status")
    op.drop_column("assessment_attempts", "final_score")
    op.drop_column("assessment_attempts", "manual_score")
