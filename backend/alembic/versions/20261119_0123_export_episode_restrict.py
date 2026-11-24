"""Deleting an episode must not turn a delivery into a project-level one (I9-02).

``exports.episode_id`` used ``ON DELETE SET NULL``, so removing an episode
silently rewrote its exports into project-level deliverables — exactly what DB09
forbids. The foreign key becomes ``RESTRICT``: an episode that already has
deliveries cannot be deleted until those deliveries are withdrawn explicitly.

Revision ID: 20261119_0123
Revises: 20261119_0122
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261119_0123"
down_revision: str | None = "20261119_0122"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_episode_fk(*, on_delete: str) -> None:
    op.execute("ALTER TABLE exports DROP CONSTRAINT IF EXISTS fk_exports_episode")
    op.execute(
        "ALTER TABLE exports ADD CONSTRAINT fk_exports_episode "
        f"FOREIGN KEY (episode_id) REFERENCES episodes (id) ON DELETE {on_delete}"
    )


def upgrade() -> None:
    _replace_episode_fk(on_delete="RESTRICT")


def downgrade() -> None:
    _replace_episode_fk(on_delete="SET NULL")
