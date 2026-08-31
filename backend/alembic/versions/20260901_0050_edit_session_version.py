"""Add optimistic versioning to edit sessions.

Revision ID: 20260901_0050
Revises: 20260827_0049
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0050"
down_revision: str | None = "20260827_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add nullable first so existing rows can be backfilled before the NOT NULL
    # contract is installed. No other edit-session data is rewritten.
    op.add_column("edit_sessions", sa.Column("version", sa.Integer(), nullable=True))
    op.execute("UPDATE edit_sessions SET version = 1 WHERE version IS NULL")
    op.alter_column(
        "edit_sessions",
        "version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("1"),
    )
    op.create_check_constraint(
        "ck_edit_sessions_version_positive",
        "edit_sessions",
        "version > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_edit_sessions_version_positive",
        "edit_sessions",
        type_="check",
    )
    op.drop_column("edit_sessions", "version")
