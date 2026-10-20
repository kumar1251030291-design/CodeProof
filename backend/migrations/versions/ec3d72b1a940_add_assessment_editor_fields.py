"""Add fields required by evaluator assessment editor APIs.

Revision ID: ec3d72b1a940
Revises: b6a3c91f204e
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ec3d72b1a940"
down_revision: Union[str, Sequence[str], None] = "b6a3c91f204e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column("instructions", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column("difficulty", sa.String(length=16), server_default="medium", nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column("points", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column("allowed_languages", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column("problem_statement", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column("examples", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column("answer_options", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column("questions", sa.Column("correct_answer", sa.Text(), nullable=True))
    op.create_check_constraint(
        "question_difficulty_valid", "questions", "difficulty IN ('easy', 'medium', 'hard')"
    )
    op.create_check_constraint("question_points_nonnegative", "questions", "points >= 0")
    op.create_unique_constraint(
        "uq_assessments_access_code_hash", "assessments", ["access_code_hash"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_assessments_access_code_hash", "assessments", type_="unique")
    op.drop_constraint("question_points_nonnegative", "questions", type_="check")
    op.drop_constraint("question_difficulty_valid", "questions", type_="check")
    op.drop_column("questions", "correct_answer")
    op.drop_column("questions", "answer_options")
    op.drop_column("questions", "examples")
    op.drop_column("questions", "problem_statement")
    op.drop_column("questions", "allowed_languages")
    op.drop_column("questions", "points")
    op.drop_column("questions", "difficulty")
    op.drop_column("assessments", "instructions")
