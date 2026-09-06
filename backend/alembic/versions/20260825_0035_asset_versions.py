"""Add immutable asset-card versions for the professional workspace.

Revision ID: 20260825_0035
Revises: 20260825_0034
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0035"
down_revision: str | None = "20260825_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("asset_id", "version_number", name="uq_asset_version_number"),
        sa.CheckConstraint("version_number > 0", name="ck_asset_version_number_positive"),
    )
    op.create_index(
        "idx_asset_versions_project_asset",
        "asset_versions",
        ["project_id", "asset_id", "version_number"],
    )
    op.execute("ALTER TABLE asset_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE asset_versions FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS asset_versions_project_scope ON asset_versions")
    op.execute(
        """
        CREATE POLICY asset_versions_project_scope ON asset_versions
        FOR ALL
        USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS asset_versions_project_scope ON asset_versions")
    op.execute("ALTER TABLE asset_versions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE asset_versions DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_asset_versions_project_asset", table_name="asset_versions")
    op.drop_table("asset_versions")
