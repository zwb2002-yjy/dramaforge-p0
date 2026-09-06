"""Phase 5 production experiments and shot experiments.

Revision ID: 20260827_0045
Revises: 20260826_0044
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0045"
down_revision: str | None = "20260826_0044"
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
        "production_experiments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("experiment_type", sa.String(32), nullable=False, server_default="model_swap"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_production_experiment_idempotency",
        ),
    )
    _enable_project_rls("production_experiments")

    op.create_table(
        "shot_experiments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "production_experiment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_shot_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("director_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("prompts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("references", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("common_controls", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("keyframe_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("video_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["production_experiment_id"],
            ["production_experiments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["keyframe_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["video_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "production_experiment_id",
            "shot_id",
            name="uq_shot_experiment_shot",
        ),
    )
    op.create_index(
        "ix_shot_experiments_shot",
        "shot_experiments",
        ["shot_id"],
    )
    _enable_project_rls("shot_experiments")


def downgrade() -> None:
    _disable_project_rls("shot_experiments")
    op.drop_index("ix_shot_experiments_shot", table_name="shot_experiments")
    op.drop_table("shot_experiments")
    _disable_project_rls("production_experiments")
    op.drop_table("production_experiments")
