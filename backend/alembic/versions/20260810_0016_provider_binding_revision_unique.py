"""Provider model binding uniqueness now includes the catalog revision.

Revision ID: 20260810_0016
Revises: 20260810_0015

A binding identifies one ``(connection, media_type, catalog_entry_id, purpose)``
so the same model can have multiple catalog revisions coexist as distinct
bindings. PostgreSQL treats NULL catalog_entry_id as distinct, so legacy rows
backfilled by 0015 (all non-null) stay unique.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260810_0016"
down_revision: str | None = "20260810_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_provider_model_binding",
        "provider_model_bindings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_provider_model_binding_revision",
        "provider_model_bindings",
        ["connection_id", "media_type", "catalog_entry_id", "purpose"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_provider_model_binding_revision",
        "provider_model_bindings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_provider_model_binding",
        "provider_model_bindings",
        ["connection_id", "media_type", "model_id", "purpose"],
    )
