"""Allow project-scoped Final Film assembly graph.

Revision ID: 20260903_0053
Revises: 20260903_0052
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op

revision: str = "20260903_0053"
down_revision: str | None = "20260903_0052"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE production_graphs DROP CONSTRAINT production_graphs_scope_type_check")
    op.execute(
        "ALTER TABLE production_graphs ADD CONSTRAINT production_graphs_scope_type_check "
        "CHECK (scope_type IN ('shot','episode','shot_experiment','project'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE production_graphs DROP CONSTRAINT production_graphs_scope_type_check")
    op.execute(
        "ALTER TABLE production_graphs ADD CONSTRAINT production_graphs_scope_type_check "
        "CHECK (scope_type IN ('shot','episode'))"
    )
