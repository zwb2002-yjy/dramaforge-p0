"""Separate discovered model identity from capability-plugin contracts.

Revision ID: 20260921_0075
Revises: 20260921_0074
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0075"
down_revision: str | None = "20260921_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_capability_evidence",
        sa.Column("connection_revision_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_provider_capability_evidence_connection_revision",
        "provider_capability_evidence",
        "provider_connection_revisions",
        ["connection_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_provider_model_binding_revision", "provider_model_bindings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_provider_model_binding_revision",
        "provider_model_bindings",
        ["connection_id", "media_type", "model_id", "purpose"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_provider_model_binding_revision", "provider_model_bindings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_provider_model_binding_revision",
        "provider_model_bindings",
        ["connection_id", "media_type", "catalog_entry_id", "purpose"],
    )
    op.drop_constraint(
        "fk_provider_capability_evidence_connection_revision",
        "provider_capability_evidence",
        type_="foreignkey",
    )
    op.drop_column("provider_capability_evidence", "connection_revision_id")
