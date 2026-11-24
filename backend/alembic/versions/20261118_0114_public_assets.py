"""Public asset publications, fixed items and project links (I5-01).

A publication freezes one adopted AssetVersion's safe display facts and its real media
items; a project link pins one publication and one local label. AssetVersion gains the
two base public columns for metadata-only variants. No private source table is exposed
through these tables; availability stays a read projection.

Revision ID: 20261118_0114
Revises: 20261118_0113
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261118_0114"
down_revision: str | None = "20261118_0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _owner_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner_scope ON {table} FOR ALL "
        "USING (owner_user_id = app.current_user_id()) "
        "WITH CHECK (owner_user_id = app.current_user_id())"
    )


def _project_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
        "USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_asset_version_scope", "asset_versions", ["id", "project_id"]
    )
    op.create_unique_constraint(
        "uq_asset_version_reference_scope",
        "asset_version_references",
        ["id", "asset_version_id", "artifact_id", "project_id"],
    )
    op.add_column("asset_versions", sa.Column("base_publication_id", sa.UUID(), nullable=True))
    op.add_column(
        "asset_versions", sa.Column("base_public_asset_link_id", sa.UUID(), nullable=True)
    )
    op.create_check_constraint(
        "ck_asset_version_public_base",
        "asset_versions",
        "(base_publication_id IS NULL) = (base_public_asset_link_id IS NULL)",
    )

    op.create_table(
        "public_asset_publications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("source_project_id", sa.UUID(), nullable=False),
        sa.Column("source_asset_id", sa.UUID(), nullable=False),
        sa.Column("source_asset_version_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("safe_name", sa.String(length=160), nullable=False),
        sa.Column("safe_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("safe_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("publication_hash", sa.CHAR(64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="available"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_public_asset_publication_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["source_project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_public_asset_publication_project",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_version_id", "source_project_id"],
            ["asset_versions.id", "asset_versions.project_id"],
            ondelete="RESTRICT", name="fk_public_asset_publication_version",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "source_asset_version_id", name="uq_public_asset_publication_version",
        ),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_public_asset_publication_owner"),
        sa.UniqueConstraint(
            "id", "source_project_id", "workspace_id", "owner_user_id",
            name="uq_public_asset_publication_scope",
        ),
        sa.UniqueConstraint(
            "id", "source_asset_version_id", "owner_user_id",
            name="uq_public_asset_publication_version_owner",
        ),
        sa.CheckConstraint(
            "status IN ('available','restricted','withdrawn')",
            name="ck_public_asset_publication_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_public_asset_publication_revision"),
        sa.CheckConstraint(
            "(status = 'withdrawn') = (withdrawn_at IS NOT NULL)",
            name="ck_public_asset_publication_withdrawn",
        ),
    )
    op.create_index(
        "ix_public_asset_publication_owner",
        "public_asset_publications",
        ["owner_user_id", "status", "kind", "id"],
    )

    op.create_table(
        "public_asset_publication_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("publication_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("source_project_id", sa.UUID(), nullable=False),
        sa.Column("source_asset_version_id", sa.UUID(), nullable=False),
        sa.Column("source_reference_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id", "source_asset_version_id", "owner_user_id"],
            [
                "public_asset_publications.id",
                "public_asset_publications.source_asset_version_id",
                "public_asset_publications.owner_user_id",
            ],
            ondelete="RESTRICT", name="fk_public_item_publication",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            [
                "source_reference_id",
                "source_asset_version_id",
                "artifact_id",
                "source_project_id",
            ],
            [
                "asset_version_references.id",
                "asset_version_references.asset_version_id",
                "asset_version_references.artifact_id",
                "asset_version_references.project_id",
            ],
            ondelete="RESTRICT", name="fk_public_item_reference",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "publication_id", "source_reference_id", name="uq_public_item_reference",
        ),
        sa.UniqueConstraint(
            "id", "publication_id", "artifact_id", "owner_user_id",
            name="uq_public_item_scope",
        ),
    )

    op.create_table(
        "project_public_asset_links",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("publication_id", sa.UUID(), nullable=False),
        sa.Column("source_asset_version_id", sa.UUID(), nullable=False),
        sa.Column("local_label", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("detached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_public_link_project",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_public_link_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id", "source_asset_version_id", "owner_user_id"],
            [
                "public_asset_publications.id",
                "public_asset_publications.source_asset_version_id",
                "public_asset_publications.owner_user_id",
            ],
            ondelete="RESTRICT", name="fk_public_link_publication",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint("project_id", "publication_id", name="uq_public_link_publication"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_public_link_request"),
        sa.UniqueConstraint(
            "id", "project_id", "publication_id", name="uq_public_link_base",
        ),
        sa.UniqueConstraint(
            "id", "project_id", "publication_id", "source_asset_version_id",
            name="uq_public_link_version_scope",
        ),
        sa.UniqueConstraint(
            "id", "project_id", "publication_id", "owner_user_id",
            name="uq_public_link_owner_scope",
        ),
        sa.CheckConstraint("version > 0", name="ck_public_link_version"),
    )
    op.create_index(
        "ix_public_link_project", "project_public_asset_links", ["project_id", "detached_at", "id"],
    )
    op.create_foreign_key(
        "fk_asset_version_public_base",
        "asset_versions",
        "project_public_asset_links",
        ["base_public_asset_link_id", "project_id", "base_publication_id"],
        ["id", "project_id", "publication_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    _owner_rls("public_asset_publications")
    _owner_rls("public_asset_publication_items")
    _project_rls("project_public_asset_links")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON public_asset_publications TO dramaforge_app"
    )
    op.execute(
        "REVOKE DELETE, TRUNCATE ON public_asset_publications FROM dramaforge_app"
    )
    op.execute(
        "GRANT SELECT, INSERT ON public_asset_publication_items TO dramaforge_app"
    )
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON public_asset_publication_items FROM dramaforge_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON project_public_asset_links TO dramaforge_app"
    )
    op.execute("REVOKE DELETE, TRUNCATE ON project_public_asset_links FROM dramaforge_app")


def downgrade() -> None:
    op.drop_constraint(
        "fk_asset_version_public_base", "asset_versions", type_="foreignkey"
    )
    for table in ("project_public_asset_links", "public_asset_publication_items",
                  "public_asset_publications"):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_scope ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_index("ix_public_link_project", table_name="project_public_asset_links")
    op.drop_table("project_public_asset_links")
    op.drop_table("public_asset_publication_items")
    op.drop_index(
        "ix_public_asset_publication_owner", table_name="public_asset_publications"
    )
    op.drop_table("public_asset_publications")
    op.drop_constraint("ck_asset_version_public_base", "asset_versions", type_="check")
    op.drop_column("asset_versions", "base_public_asset_link_id")
    op.drop_column("asset_versions", "base_publication_id")
    op.drop_constraint(
        "uq_asset_version_reference_scope", "asset_version_references", type_="unique"
    )
    op.drop_constraint("uq_asset_version_scope", "asset_versions", type_="unique")
