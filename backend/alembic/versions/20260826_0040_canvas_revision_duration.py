"""Version shot duration with each professional canvas revision.

Revision ID: 20260826_0040
Revises: 20260825_0039
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0040"
down_revision: str | None = "20260825_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "canvas_revisions",
        sa.Column(
            "duration_seconds",
            sa.Numeric(8, 3),
            nullable=False,
            server_default=sa.text("3"),
        ),
    )
    op.create_check_constraint(
        "ck_canvas_revision_duration_positive",
        "canvas_revisions",
        "duration_seconds > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_canvas_revision_duration_positive",
        "canvas_revisions",
        type_="check",
    )
    op.drop_column("canvas_revisions", "duration_seconds")
