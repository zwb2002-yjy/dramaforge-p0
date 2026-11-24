"""Asset version candidate receipts: one keyed candidate decision per Asset revision.

The candidate creation records its request key/hash on the new AssetVersion, so a
retry returns the original CandidateReceipt and a stale editor is refused instead of
silently creating a second candidate.

Revision ID: 20261118_0117
Revises: 20261118_0116
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_0117"
down_revision: str | None = "20261118_0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asset_versions", sa.Column("creation_request_key", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "asset_versions", sa.Column("creation_request_hash", sa.CHAR(64), nullable=True)
    )
    op.create_check_constraint(
        "ck_asset_version_creation_all_or_none",
        "asset_versions",
        "(creation_request_key IS NULL) = (creation_request_hash IS NULL)",
    )
    op.create_index(
        "uq_asset_version_creation_key",
        "asset_versions",
        ["project_id", "creation_request_key"],
        unique=True,
        postgresql_where=sa.text("creation_request_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_asset_version_creation_key", table_name="asset_versions")
    op.drop_constraint(
        "ck_asset_version_creation_all_or_none", "asset_versions", type_="check"
    )
    op.drop_column("asset_versions", "creation_request_hash")
    op.drop_column("asset_versions", "creation_request_key")
