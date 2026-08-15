"""Remove the first-release biometric identity contract.

Revision ID: 20260813_0025
Revises: 20260813_0024
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_0025"
down_revision: str | None = "20260813_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("character_references", "embedding_model_version")
    op.drop_column("character_references", "face_embedding")
    op.drop_column("characters", "similarity_threshold")


def downgrade() -> None:
    raise RuntimeError(
        "20260813_0025 is intentionally irreversible; the removed biometric contract "
        "must not be restored by downgrade"
    )
