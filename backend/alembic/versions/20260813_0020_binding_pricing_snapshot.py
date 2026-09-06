"""add owner-verified binding pricing snapshots

Revision ID: 20260813_0020
Revises: 20260813_0019
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260813_0020"
down_revision = "20260813_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_model_bindings",
        sa.Column(
            "pricing_snapshot_json",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_model_bindings", "pricing_snapshot_json")
