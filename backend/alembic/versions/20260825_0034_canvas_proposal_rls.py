"""Scope professional canvas revisions and change proposals to the current project.

Revision ID: 20260825_0034
Revises: 20260825_0033
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0034"
down_revision: str | None = "20260825_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("canvas_revisions", "shot_change_proposals")


def upgrade() -> None:
    for table in _TABLES:
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


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")