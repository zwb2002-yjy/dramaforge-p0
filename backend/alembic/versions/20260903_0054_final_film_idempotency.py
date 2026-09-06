"""Add an explicit idempotency key to exports.

Revision ID: 20260903_0054
Revises: 20260903_0053
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0054"
down_revision: str | None = "20260903_0053"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("exports", sa.Column("idempotency_key", sa.String(200), nullable=True))
    # Preserve keys already written by the first Final Film implementation so
    # a retry after migration cannot create a duplicate export.
    op.execute(
        sa.text(
            "UPDATE exports SET idempotency_key = manifest->>'idempotency_key' "
            "WHERE idempotency_key IS NULL "
            "AND format = 'dramaforge-final-film-v1' "
            "AND manifest ? 'idempotency_key'"
        )
    )
    op.create_index(
        "uq_exports_project_format_idempotency",
        "exports",
        ["project_id", "format", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_exports_project_format_idempotency", table_name="exports")
    op.drop_column("exports", "idempotency_key")
