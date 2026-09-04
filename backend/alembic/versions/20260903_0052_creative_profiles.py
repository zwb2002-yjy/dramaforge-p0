"""Add project creative profiles.

Revision ID: 20260903_0052
Revises: 20260902_0051
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260903_0052"
down_revision: str | None = "20260902_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def upgrade() -> None:
    op.create_table(
        "project_creative_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_type", sa.String(16), nullable=False, server_default="FREE"),
        sa.Column("created_from_template_key", sa.String(80), nullable=True),
        sa.Column("template_version", sa.String(40), nullable=True),
        sa.Column("template_contract_hash", sa.String(64), nullable=True),
        sa.Column("director_autonomy", sa.String(16), nullable=False, server_default="ASSIST"),
        sa.Column("selected_genre", sa.String(80), nullable=True),
        sa.Column(
            "selected_style_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "selected_skill_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("selected_shot_language", sa.String(80), nullable=True),
        sa.Column(
            "asset_slot_requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "strategy_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", name="uq_project_creative_profile_project"),
    )
    _enable_project_rls("project_creative_profiles")
    op.execute(
        """
        INSERT INTO project_creative_profiles (project_id, start_type)
        SELECT id, 'FREE' FROM projects
        ON CONFLICT (project_id) DO NOTHING
        """
    )


def downgrade() -> None:
    _disable_project_rls("project_creative_profiles")
    op.drop_table("project_creative_profiles")
