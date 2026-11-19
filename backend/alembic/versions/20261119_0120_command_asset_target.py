"""Command authorizations can target a shot or an asset (I8a-03).

Asset media production reuses the same one-command grant, receipt and Worker path
as shot commands. A grant names exactly one target; the existing shot-only rows
keep ``asset_id`` NULL.

Revision ID: 20261119_0120
Revises: 20261118_0119
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_0120"
down_revision: str | None = "20261118_0119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "production_command_authorizations",
        "shot_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.add_column(
        "production_command_authorizations",
        sa.Column("asset_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_command_auth_asset",
        "production_command_authorizations",
        "assets",
        ["asset_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_command_auth_target",
        "production_command_authorizations",
        "(shot_id IS NOT NULL AND asset_id IS NULL) OR "
        "(shot_id IS NULL AND asset_id IS NOT NULL)",
    )
    op.create_index(
        "ix_command_auth_asset",
        "production_command_authorizations",
        ["asset_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_command_auth_asset", table_name="production_command_authorizations")
    op.drop_constraint(
        "ck_command_auth_target",
        "production_command_authorizations",
        type_="check",
    )
    op.drop_constraint(
        "fk_command_auth_asset",
        "production_command_authorizations",
        type_="foreignkey",
    )
    op.drop_column("production_command_authorizations", "asset_id")
    op.alter_column(
        "production_command_authorizations",
        "shot_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
