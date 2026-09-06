"""Add a non-sensitive singleton for first-Owner bootstrap.

Revision ID: 20260813_0019
Revises: 20260813_0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0019"
down_revision: str | None = "20260813_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instance_bootstrap_state",
        sa.Column("singleton_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "singleton_id = 1", name="ck_instance_bootstrap_state_singleton"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("singleton_id"),
        sa.UniqueConstraint("owner_user_id"),
    )
    # Existing deployments already have users. The migration connection is the
    # trusted schema owner and can choose the oldest account as the initialized
    # Owner without exposing user rows through the public runtime endpoint.
    op.execute(
        """
        INSERT INTO instance_bootstrap_state (singleton_id, owner_user_id)
        SELECT 1, id
        FROM users
        ORDER BY created_at, id
        LIMIT 1
        """
    )


def downgrade() -> None:
    op.drop_table("instance_bootstrap_state")
