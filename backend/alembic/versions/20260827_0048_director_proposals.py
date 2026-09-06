"""Director Assistant proposal tables.

Revision ID: 20260827_0048
Revises: 20260827_0047
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0048"
down_revision: str | None = "20260827_0047"
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
        "director_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["director_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_director_proposals_scope", "director_proposals", ["scope_type", "scope_entity_id"])
    _enable_project_rls("director_proposals")

    op.create_table(
        "director_proposal_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expected_target_version", sa.Integer(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("benefit", sa.Text(), nullable=False, server_default=""),
        sa.Column("cost", sa.Text(), nullable=False, server_default=""),
        sa.Column("risk", sa.Text(), nullable=False, server_default=""),
        sa.Column("impact", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["proposal_id"], ["director_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_director_proposal_items_proposal", "director_proposal_items", ["proposal_id"])
    _enable_project_rls("director_proposal_items")


def downgrade() -> None:
    _disable_project_rls("director_proposal_items")
    op.drop_index("ix_director_proposal_items_proposal", table_name="director_proposal_items")
    op.drop_table("director_proposal_items")
    _disable_project_rls("director_proposals")
    op.drop_index("ix_director_proposals_scope", table_name="director_proposals")
    op.drop_table("director_proposals")
