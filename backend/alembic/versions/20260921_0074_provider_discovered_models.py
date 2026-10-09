"""Persist model ids returned by account catalog probes.

Revision ID: 20260921_0074
Revises: 20260919_0073
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0074"
down_revision: str | None = "20260919_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_capability_evidence",
        sa.Column(
            "discovered_model_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_capability_evidence", "discovered_model_ids")
