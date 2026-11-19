"""Asset version adoption receipts: promote is one CAS decision with a replay (I5-02).

The adoption fact lives on the promoted AssetVersion (request key/hash + the Asset row
revision it accepted), so a replay returns the original receipt and a second adoption
with a new key is refused instead of silently re-switching the current version.

Revision ID: 20261118_0116
Revises: 20261118_0115
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_0116"
down_revision: str | None = "20261118_0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asset_versions", sa.Column("adoption_request_key", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "asset_versions", sa.Column("adoption_request_hash", sa.CHAR(64), nullable=True)
    )
    op.add_column(
        "asset_versions", sa.Column("adopted_asset_revision", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_asset_version_adoption_all_or_none",
        "asset_versions",
        "(adoption_request_key IS NULL) = (adoption_request_hash IS NULL) "
        "AND (adoption_request_key IS NULL) = (adopted_asset_revision IS NULL)",
    )
    op.create_index(
        "uq_asset_version_adoption_key",
        "asset_versions",
        ["project_id", "adoption_request_key"],
        unique=True,
        postgresql_where=sa.text("adoption_request_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_asset_version_adoption_key", table_name="asset_versions")
    op.drop_constraint(
        "ck_asset_version_adoption_all_or_none", "asset_versions", type_="check"
    )
    op.drop_column("asset_versions", "adopted_asset_revision")
    op.drop_column("asset_versions", "adoption_request_hash")
    op.drop_column("asset_versions", "adoption_request_key")
