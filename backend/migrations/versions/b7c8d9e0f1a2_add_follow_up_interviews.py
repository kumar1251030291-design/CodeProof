"""Add persistent candidate follow-up interviews.

Revision ID: b7c8d9e0f1a2
Revises: f1a2b3c4d5e6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "follow_up_interviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("review_score", sa.Integer(), nullable=True),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'in_progress', 'submitted', 'reviewed')", name="follow_up_status_valid"),
        sa.CheckConstraint("review_score IS NULL OR review_score BETWEEN 0 AND 100", name="follow_up_score_valid"),
        sa.ForeignKeyConstraint(["attempt_id"], ["assessment_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["user_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_follow_up_interviews_attempt"),
    )
    op.create_index("ix_follow_up_candidate", "follow_up_interviews", ["candidate_id", "created_at"])
    op.create_table(
        "follow_up_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("answer", sa.Text(), server_default="", nullable=False),
        sa.Column("answer_locked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("origin IN ('ai', 'evaluator')", name="follow_up_origin_valid"),
        sa.CheckConstraint("length(trim(prompt)) > 0", name="follow_up_prompt_nonempty"),
        sa.CheckConstraint("length(answer) <= 20000", name="follow_up_answer_length"),
        sa.ForeignKeyConstraint(["interview_id"], ["follow_up_interviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_follow_up_question_interview", "follow_up_questions", ["interview_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_follow_up_question_interview", table_name="follow_up_questions")
    op.drop_table("follow_up_questions")
    op.drop_index("ix_follow_up_candidate", table_name="follow_up_interviews")
    op.drop_table("follow_up_interviews")
