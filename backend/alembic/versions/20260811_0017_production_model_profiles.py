"""Production model profiles (multi-model production configuration).

Revision ID: 20260811_0017
Revises: 20260810_0016
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0017"
down_revision: str | None = "20260810_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _workspace_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_workspace_scope ON {table}
        FOR ALL
        USING (
          workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = {table}.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
        )
        WITH CHECK (
          workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = {table}.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "production_model_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("bindings", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "workspace_id", "name", "project_id", name="uq_model_profile_workspace_name"
        ),
        sa.UniqueConstraint("project_id", name="uq_model_profile_project"),
    )
    op.create_index(
        "ix_production_model_profiles_workspace_id",
        "production_model_profiles",
        ["workspace_id"],
    )
    # At most one workspace default per workspace (project_id IS NULL).
    op.create_index(
        "uq_model_profile_workspace_default",
        "production_model_profiles",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND project_id IS NULL"),
    )
    _workspace_rls("production_model_profiles")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS production_model_profiles_workspace_scope ON production_model_profiles")
    op.drop_table("production_model_profiles")
