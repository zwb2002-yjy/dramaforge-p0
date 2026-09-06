"""Exports, export_items, shot_human_locks.

Revision ID: 20260721_0006
Revises: 20260721_0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0006"
down_revision: str | None = "20260721_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    export_format = postgresql.ENUM(
        "mp4",
        "srt",
        "asset_package",
        "timeline_json",
        "jianying_draft",
        "davinci_fcpxml",
        "edl",
        "aaf",
        name="export_format",
        create_type=False,
    )
    export_status = postgresql.ENUM(
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        name="export_status",
        create_type=False,
    )
    export_format.create(op.get_bind(), checkfirst=True)
    export_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("format", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("result_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "export_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("export_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["export_id"], ["exports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("export_id", "ordinal", name="uq_export_item_ordinal"),
        sa.CheckConstraint("ordinal > 0"),
    )
    op.create_table(
        "shot_human_locks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locked", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("locked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["locked_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "shot_id", name="uq_shot_lock"),
    )
    for table in ("exports", "export_items", "shot_human_locks"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS exports_project_scope ON exports")
    op.execute(
        """
        CREATE POLICY exports_project_scope ON exports
        FOR ALL USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
        """
    )
    op.execute("DROP POLICY IF EXISTS export_items_project_scope ON export_items")
    op.execute(
        """
        CREATE POLICY export_items_project_scope ON export_items
        FOR ALL USING (
          EXISTS (
            SELECT 1 FROM exports e WHERE e.id = export_items.export_id
              AND e.project_id = app.current_project_id()
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1 FROM exports e WHERE e.id = export_items.export_id
              AND e.project_id = app.current_project_id()
          )
        )
        """
    )
    op.execute("DROP POLICY IF EXISTS shot_human_locks_project_scope ON shot_human_locks")
    op.execute(
        """
        CREATE POLICY shot_human_locks_project_scope ON shot_human_locks
        FOR ALL USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
        """
    )


def downgrade() -> None:
    op.drop_table("shot_human_locks")
    op.drop_table("export_items")
    op.drop_table("exports")
