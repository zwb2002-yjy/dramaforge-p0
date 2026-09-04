"""Add per-shot 2D and rough-3D director board state.

Revision ID: 20260825_0038
Revises: 20260825_0037
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0038"
down_revision: str | None = "20260825_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "director_board_states",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="2d"),
        sa.Column(
            "camera",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "characters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "scene",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("shot_id", name="uq_director_board_shot"),
        sa.CheckConstraint("version > 0", name="ck_director_board_version_positive"),
    )
    op.execute("ALTER TABLE director_board_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE director_board_states FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY director_board_states_project_scope ON director_board_states FOR ALL USING (project_id = app.current_project_id()) WITH CHECK (project_id = app.current_project_id())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS director_board_states_project_scope ON director_board_states")
    op.execute("ALTER TABLE director_board_states NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE director_board_states DISABLE ROW LEVEL SECURITY")
    op.drop_table("director_board_states")
