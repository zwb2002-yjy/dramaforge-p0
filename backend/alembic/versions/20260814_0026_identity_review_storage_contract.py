"""Add storage support for the identity-review contract.

Revision ID: 20260814_0026
Revises: 20260813_0025
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0026"
down_revision: str | None = "20260813_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE node_type ADD VALUE IF NOT EXISTS "
        "'identity_review' AFTER 'keyframe'"
    )
    op.alter_column(
        "characters",
        "calibration_state",
        type_=sa.String(length=32),
        existing_type=sa.String(length=16),
        existing_nullable=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260814_0026 is intentionally irreversible; PostgreSQL enum values and "
        "persisted identity-review states cannot be removed safely"
    )
