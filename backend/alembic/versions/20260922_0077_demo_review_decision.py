"""Separate demo-flow confirmation from human quality approval.

Revision ID: 20260922_0077
Revises: 20260921_0076
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260922_0077"
down_revision: str | None = "20260921_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_human_review_decision_value",
        "human_review_decisions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_human_review_decision_value",
        "human_review_decisions",
        "decision IN ('approved','rejected','demo_confirmed')",
    )


def downgrade() -> None:
    # PostgreSQL will reject this downgrade while demo-only rows still exist.
    op.drop_constraint(
        "ck_human_review_decision_value",
        "human_review_decisions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_human_review_decision_value",
        "human_review_decisions",
        "decision IN ('approved','rejected')",
    )
