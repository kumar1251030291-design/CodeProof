"""Add restricted assessment grants and candidate attempt persistence.

Revision ID: a91e8e61bc30
Revises: ec3d72b1a940
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a91e8e61bc30"
down_revision: Union[str, Sequence[str], None] = "ec3d72b1a940"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assessment_access_grants",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["user_profiles.id"], ondelete="CASCADE", name="fk_access_grant_candidate"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE", name="fk_access_grant_assessment"),
        sa.PrimaryKeyConstraint("candidate_id", "assessment_id", name=None),
    )
    op.create_index("ix_assessment_access_grants_expiry", "assessment_access_grants", ["expires_at"])

    op.create_table(
        "access_code_rate_limits",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("failed_attempts >= 0", name="rate_failures_nonnegative"),
        sa.ForeignKeyConstraint(["candidate_id"], ["user_profiles.id"], ondelete="CASCADE", name="fk_code_limit_candidate"),
        sa.PrimaryKeyConstraint("candidate_id", name=None),
    )

    op.create_table(
        "assessment_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="in_progress", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        sa.CheckConstraint("status IN ('in_progress', 'submitted', 'expired')", name="attempt_status_valid"),
        sa.ForeignKeyConstraint(["candidate_id"], ["user_profiles.id"], ondelete="CASCADE", name="fk_attempt_candidate"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE", name="fk_attempt_assessment"),
        sa.PrimaryKeyConstraint("id", name=None),
        sa.UniqueConstraint("candidate_id", "assessment_id", "attempt_number", name="uq_attempt_candidate_number"),
    )
    op.create_index("ix_attempts_candidate_started", "assessment_attempts", ["candidate_id", "started_at"])
    op.create_index("ix_attempts_assessment_candidate", "assessment_attempts", ["assessment_id", "candidate_id"])

    op.create_table(
        "attempt_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("response_text", sa.Text(), server_default="", nullable=False),
        sa.Column("programming_language", sa.String(length=16), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("programming_language IS NULL OR programming_language IN ('python', 'c')", name="response_language_valid"),
        sa.ForeignKeyConstraint(["attempt_id"], ["assessment_attempts.id"], ondelete="CASCADE", name="fk_response_attempt"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE", name="fk_response_question"),
        sa.PrimaryKeyConstraint("id", name=None),
        sa.UniqueConstraint("attempt_id", "question_id", name="uq_attempt_response_question"),
    )


def downgrade() -> None:
    op.drop_table("attempt_responses")
    op.drop_index("ix_attempts_assessment_candidate", table_name="assessment_attempts")
    op.drop_index("ix_attempts_candidate_started", table_name="assessment_attempts")
    op.drop_table("assessment_attempts")
    op.drop_table("access_code_rate_limits")
    op.drop_index("ix_assessment_access_grants_expiry", table_name="assessment_access_grants")
    op.drop_table("assessment_access_grants")
