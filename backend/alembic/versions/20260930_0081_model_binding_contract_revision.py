"""Allow one discovered model to retain separate immutable contract bindings.

Revision ID: 20260930_0081
Revises: 20260930_0080
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260930_0081"
down_revision: str | None = "20260930_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_provider_model_binding_revision", "provider_model_bindings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_provider_model_binding_revision",
        "provider_model_bindings",
        ["connection_id", "media_type", "model_id", "purpose", "catalog_entry_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_provider_model_binding_revision", "provider_model_bindings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_provider_model_binding_revision",
        "provider_model_bindings",
        ["connection_id", "media_type", "model_id", "purpose"],
    )
