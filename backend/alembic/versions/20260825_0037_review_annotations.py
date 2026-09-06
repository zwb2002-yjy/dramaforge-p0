"""Add time-range review annotations for shot evidence.

Revision ID: 20260825_0037
Revises: 20260825_0036
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0037"
down_revision: str | None = "20260825_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_annotations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_start", sa.Numeric(10, 3), nullable=True),
        sa.Column("time_end", sa.Numeric(10, 3), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="note"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "time_start IS NULL OR time_start >= 0", name="ck_review_annotation_start_nonnegative"
        ),
        sa.CheckConstraint(
            "time_end IS NULL OR time_end >= 0", name="ck_review_annotation_end_nonnegative"
        ),
        sa.CheckConstraint(
            "time_end IS NULL OR time_start IS NULL OR time_end >= time_start",
            name="ck_review_annotation_range",
        ),
    )
    op.create_index(
        "idx_review_annotations_project_shot",
        "review_annotations",
        ["project_id", "shot_id", "created_at"],
    )
    op.execute("ALTER TABLE review_annotations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_annotations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY review_annotations_project_scope ON review_annotations FOR ALL USING (project_id = app.current_project_id()) WITH CHECK (project_id = app.current_project_id())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS review_annotations_project_scope ON review_annotations")
    op.execute("ALTER TABLE review_annotations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_annotations DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_review_annotations_project_shot", table_name="review_annotations")
    op.drop_table("review_annotations")
