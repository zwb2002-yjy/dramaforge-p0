"""Add reviewable assistant proposals for shot canvas changes.

Revision ID: 20260825_0033
Revises: 20260825_0032
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0033"
down_revision: str | None = "20260825_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shot_change_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("base_shot_version", sa.Integer(), nullable=False),
        sa.Column("replacement_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("affected_node_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reusable_artifact_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(24), nullable=False, server_default="awaiting_confirmation"),
        sa.Column("confirmed_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["confirmed_revision_id"], ["canvas_revisions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_shot_change_proposal_idempotency"),
        sa.CheckConstraint("base_shot_version > 0", name="ck_shot_change_proposal_base_version_positive"),
    )
    op.create_index("idx_shot_change_proposals_project_shot", "shot_change_proposals", ["project_id", "shot_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_shot_change_proposals_project_shot", table_name="shot_change_proposals")
    op.drop_table("shot_change_proposals")