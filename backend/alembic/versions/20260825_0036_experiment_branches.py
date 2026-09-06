"""Add formal/experimental execution branches.

Revision ID: 20260825_0036
Revises: 20260825_0035
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0036"
down_revision: str | None = "20260825_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_branches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_shot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("branch_type", sa.String(32), nullable=False, server_default="model_experiment"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column(
            "source_artifact_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "candidate_artifact_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "comparison",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "adopted_shot_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("selected_model", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_shot_id"], ["shots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id", "idempotency_key", name="uq_experiment_branch_idempotency"
        ),
    )
    op.create_index(
        "idx_experiment_branches_project", "experiment_branches", ["project_id", "created_at"]
    )
    op.execute("ALTER TABLE experiment_branches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE experiment_branches FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY experiment_branches_project_scope ON experiment_branches FOR ALL USING (project_id = app.current_project_id()) WITH CHECK (project_id = app.current_project_id())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS experiment_branches_project_scope ON experiment_branches")
    op.execute("ALTER TABLE experiment_branches NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE experiment_branches DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_experiment_branches_project", table_name="experiment_branches")
    op.drop_table("experiment_branches")

