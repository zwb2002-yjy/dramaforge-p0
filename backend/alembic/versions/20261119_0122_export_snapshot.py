"""Exports bind an immutable edit-session snapshot (I9-02).

An export must point at the exact timeline version it froze, not at whatever the
session holds later. The composite foreign key reuses the ``(id, project_id)``
candidate key, so an export can never name a session from another project.

Revision ID: 20261119_0122
Revises: 20261119_0121
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_0122"
down_revision: str | None = "20261119_0121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("exports", sa.Column("edit_session_id", sa.UUID(), nullable=True))
    op.add_column("exports", sa.Column("timeline_version", sa.Integer(), nullable=True))
    op.add_column("exports", sa.Column("timeline_hash", sa.CHAR(64), nullable=True))
    op.add_column("exports", sa.Column("render_node_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_exports_edit_session",
        "exports",
        "edit_sessions",
        ["edit_session_id", "project_id"],
        ["id", "project_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_exports_render_node_run",
        "exports",
        "node_runs",
        ["render_node_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_exports_session_timeline",
        "exports",
        ["edit_session_id", "timeline_version"],
    )
    op.create_index("ix_exports_render_node_run", "exports", ["render_node_run_id"])
    op.create_index(
        "ix_exports_project_episode_created",
        "exports",
        ["project_id", "episode_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_exports_project_episode_created", table_name="exports")
    op.drop_index("ix_exports_render_node_run", table_name="exports")
    op.drop_index("ix_exports_session_timeline", table_name="exports")
    op.drop_constraint("fk_exports_render_node_run", "exports", type_="foreignkey")
    op.drop_constraint("fk_exports_edit_session", "exports", type_="foreignkey")
    op.drop_column("exports", "render_node_run_id")
    op.drop_column("exports", "timeline_hash")
    op.drop_column("exports", "timeline_version")
    op.drop_column("exports", "edit_session_id")
