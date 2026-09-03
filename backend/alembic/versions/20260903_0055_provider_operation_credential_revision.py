"""Persist credential revision identity on ProviderOperation.

Revision ID: 20260903_0055
Revises: 20260903_0054
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260903_0055"
down_revision: str | None = "20260903_0054"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_operations",
        sa.Column("credential_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_provider_operations_credential_revision_id",
        "provider_operations",
        ["credential_revision_id"],
    )
    op.create_foreign_key(
        "fk_provider_operations_credential_revision",
        "provider_operations",
        "encrypted_provider_credentials",
        ["credential_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_provider_operations_credential_revision",
        "provider_operations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_provider_operations_credential_revision_id",
        table_name="provider_operations",
    )
    op.drop_column("provider_operations", "credential_revision_id")
