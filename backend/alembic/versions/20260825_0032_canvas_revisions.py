"""Add immutable shot canvas revisions for the professional workbench.

Revision ID: 20260825_0032
Revises: 20260821_0031
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0032"
down_revision: str | None = "20260821_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canvas_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("base_shot_version", sa.Integer(), nullable=False),
        sa.Column("visual_description", sa.Text(), nullable=False),
        sa.Column("shot_type", sa.String(40), nullable=False),
        sa.Column("camera_move", sa.String(80), nullable=False),
        sa.Column("dialogue", sa.Text(), server_default="", nullable=False),
        sa.Column("source", sa.String(24), server_default="user", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("shot_id", "revision_number", name="uq_canvas_revision_number"),
        sa.CheckConstraint("revision_number > 0", name="ck_canvas_revision_number_positive"),
        sa.CheckConstraint("base_shot_version > 0", name="ck_canvas_revision_base_version_positive"),
    )
    op.create_index("idx_canvas_revisions_project_shot", "canvas_revisions", ["project_id", "shot_id", "revision_number"])


def downgrade() -> None:
    op.drop_index("idx_canvas_revisions_project_shot", table_name="canvas_revisions")
    op.drop_table("canvas_revisions")