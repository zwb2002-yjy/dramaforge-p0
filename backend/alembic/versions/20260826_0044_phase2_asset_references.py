"""Phase 2 structured asset references, tags, and shot bindings.

Revision ID: 20260826_0044
Revises: 20260826_0043
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0044"
down_revision: str | None = "20260826_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWN_ROLES = (
    "front_face",
    "three_quarter",
    "profile",
    "half_body",
    "full_body",
    "expression",
    "outfit",
    "primary",
    "action_reference",
    "camera_reference",
    "scene_reference",
    "layout_reference",
    "lighting_reference",
    "style_reference",
)


def _enable_project_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
    op.execute(
        f"""
        CREATE POLICY {table}_project_scope ON {table}
        FOR ALL
        USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
        """
    )


def _disable_project_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _enable_asset_tag_links_rls() -> None:
    """Project-scope asset_tag_links via its tag (junction has no project_id).

    Mirrors the existing character_references junction pattern: the policy
    resolves the current project through the linked asset_tags row instead of
    a direct project_id column.
    """
    op.execute("ALTER TABLE asset_tag_links ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE asset_tag_links FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS asset_tag_links_project_scope ON asset_tag_links")
    op.execute(
        """
        CREATE POLICY asset_tag_links_project_scope ON asset_tag_links
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM asset_tags t
                WHERE t.id = asset_tag_links.tag_id
                  AND t.project_id = app.current_project_id()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM asset_tags t
                WHERE t.id = asset_tag_links.tag_id
                  AND t.project_id = app.current_project_id()
            )
        )
        """
    )



def upgrade() -> None:
    op.create_table(
        "asset_version_references",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_role", sa.String(40), nullable=False),
        sa.Column("label", sa.String(160), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["artifacts.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "asset_version_id",
            "artifact_id",
            name="uq_asset_version_reference_artifact",
        ),
    )
    op.create_index(
        "ix_asset_version_references_version",
        "asset_version_references",
        ["asset_version_id"],
    )
    _enable_project_rls("asset_version_references")

    op.create_table(
        "asset_tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("normalized_name", sa.String(80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "project_id", "normalized_name", name="uq_asset_tag_project_name"
        ),
    )
    _enable_project_rls("asset_tags")

    op.create_table(
        "asset_tag_links",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["asset_tags.id"], ondelete="CASCADE"),
    )
    _enable_asset_tag_links_rls()

    op.create_table(
        "shot_reference_bindings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_experiment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage", sa.String(16), nullable=False, server_default="both"),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "resolution_mode", sa.String(24), nullable=False, server_default="current_formal"
        ),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("label", sa.String(160), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["shot_experiment_id"], ["experiment_branches.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "asset_id IS NOT NULL OR asset_version_id IS NOT NULL OR artifact_id IS NOT NULL",
            name="ck_shot_reference_binding_source",
        ),
        sa.CheckConstraint(
            "(resolution_mode <> 'direct_artifact') OR artifact_id IS NOT NULL",
            name="ck_shot_reference_binding_direct_artifact",
        ),
        sa.CheckConstraint(
            "(resolution_mode <> 'pinned_version') OR asset_version_id IS NOT NULL",
            name="ck_shot_reference_binding_pinned_version",
        ),
        sa.CheckConstraint(
            "(resolution_mode <> 'current_formal') OR asset_id IS NOT NULL",
            name="ck_shot_reference_binding_current_formal",
        ),
        sa.CheckConstraint(
            "stage IN ('image', 'video', 'both')",
            name="ck_shot_reference_binding_stage",
        ),
        sa.CheckConstraint(
            "resolution_mode IN ('current_formal', 'pinned_version', 'direct_artifact')",
            name="ck_shot_reference_binding_resolution_mode",
        ),
        sa.CheckConstraint(
            "purpose IN ('identity', 'clothing', 'scene_layout', 'scene_lighting', "
            "'style', 'action', 'pose', 'camera_language', 'audio_rhythm', "
            "'first_frame', 'last_frame', 'generic_reference')",
            name="ck_shot_reference_binding_purpose",
        ),
    )
    op.create_index(
        "ix_shot_reference_bindings_shot",
        "shot_reference_bindings",
        ["shot_id"],
    )
    _enable_project_rls("shot_reference_bindings")

    # Backfill: each existing Character becomes an immutable AssetVersion v1
    # (formal) with its CharacterReference rows mapped to AssetVersionReference.
    # Legacy CharacterReference stays readable during the migration window.
    op.execute(
        """
        INSERT INTO asset_versions
          (id, project_id, asset_id, version_number, kind, name, description,
           metadata, status, created_by, created_at)
        SELECT
          gen_random_uuid(), a.project_id, a.id, 1, a.kind, a.name, a.description,
          a.metadata, 'formal',
          (SELECT w.owner_user_id FROM workspaces w WHERE w.id = p.workspace_id),
          now()
        FROM characters c
        JOIN assets a ON a.id = c.id
        JOIN projects p ON p.id = a.project_id
        WHERE NOT EXISTS (
          SELECT 1 FROM asset_versions av
          WHERE av.asset_id = a.id AND av.version_number = 1
        )
        """
    )
    op.execute(
        """
        UPDATE assets a
        SET current_version_id = v.id
        FROM asset_versions v
        WHERE v.asset_id = a.id
          AND v.version_number = 1
          AND v.status = 'formal'
          AND a.current_version_id IS NULL
        """
    )
    op.execute(
        f"""
        INSERT INTO asset_version_references
          (id, project_id, asset_version_id, artifact_id, reference_role,
           label, sort_order, metadata, created_at)
        SELECT
          gen_random_uuid(), v.project_id, v.id, cr.artifact_id,
          CASE
            WHEN cr.is_canonical THEN 'primary'
            WHEN cr.reference_kind IN {_KNOWN_ROLES!r} THEN cr.reference_kind
            ELSE 'primary'
          END,
          '', 0, '{{}}'::jsonb, cr.created_at
        FROM character_references cr
        JOIN asset_versions v
          ON v.asset_id = cr.character_id AND v.version_number = 1
        WHERE cr.artifact_id IS NOT NULL
        """
    )


def downgrade() -> None:
    _disable_project_rls("shot_reference_bindings")
    op.drop_index("ix_shot_reference_bindings_shot", table_name="shot_reference_bindings")
    op.drop_table("shot_reference_bindings")

    _disable_project_rls("asset_tag_links")
    op.drop_table("asset_tag_links")

    _disable_project_rls("asset_tags")
    op.drop_table("asset_tags")

    _disable_project_rls("asset_version_references")
    op.drop_index(
        "ix_asset_version_references_version",
        table_name="asset_version_references",
    )
    op.drop_table("asset_version_references")
