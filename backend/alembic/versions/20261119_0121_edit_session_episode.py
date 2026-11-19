"""Edit sessions gain an optional episode scope (I9-01).

Per-episode delivery needs a session that is bound to exactly one episode, while
every existing session keeps its project-wide meaning with ``episode_id`` NULL.
The candidate key and index support episode-scoped export binding without
reinterpreting historical rows.

Revision ID: 20261119_0121
Revises: 20261119_0120
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_0121"
down_revision: str | None = "20261119_0120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("edit_sessions", sa.Column("episode_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_edit_sessions_episode",
        "edit_sessions",
        "episodes",
        ["episode_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_edit_sessions_id_project",
        "edit_sessions",
        ["id", "project_id"],
    )
    op.create_index(
        "ix_edit_sessions_project_episode",
        "edit_sessions",
        ["project_id", "episode_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_edit_sessions_project_episode", table_name="edit_sessions")
    op.drop_constraint("uq_edit_sessions_id_project", "edit_sessions", type_="unique")
    op.drop_constraint("fk_edit_sessions_episode", "edit_sessions", type_="foreignkey")
    op.drop_column("edit_sessions", "episode_id")
