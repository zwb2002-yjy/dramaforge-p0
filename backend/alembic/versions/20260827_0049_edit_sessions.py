"""Phase 9 edit session tables.

Revision ID: 20260827_0049
Revises: 20260827_0048
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0049"
down_revision: str | None = "20260827_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edit_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default="Edit"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("production_lineage", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.execute("ALTER TABLE edit_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edit_sessions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY edit_sessions_project_scope ON edit_sessions "
        "FOR ALL USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS edit_sessions_project_scope ON edit_sessions")
    op.execute("ALTER TABLE edit_sessions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edit_sessions DISABLE ROW LEVEL SECURITY")
    op.drop_table("edit_sessions")
