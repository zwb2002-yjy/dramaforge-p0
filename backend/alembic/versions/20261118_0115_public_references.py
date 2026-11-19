"""Public-link shot references: a binding may pin a project link and one item (I5-02).

The binding keeps exactly one source: private asset/version/artifact fields or a
project public link + publication item. Public bindings resolve through the link and
never carry source project identities.

Revision ID: 20261118_0115
Revises: 20261118_0114
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_0115"
down_revision: str | None = "20261118_0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_public_link_project_scope",
        "project_public_asset_links",
        ["id", "project_id"],
    )
    op.add_column(
        "shot_reference_bindings",
        sa.Column("public_asset_link_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "shot_reference_bindings",
        sa.Column("publication_item_id", sa.UUID(), nullable=True),
    )
    op.drop_constraint(
        "ck_shot_reference_binding_source", "shot_reference_bindings", type_="check"
    )
    op.create_check_constraint(
        "ck_shot_reference_binding_source",
        "shot_reference_bindings",
        "(public_asset_link_id IS NOT NULL) OR asset_id IS NOT NULL "
        "OR asset_version_id IS NOT NULL OR artifact_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_shot_reference_binding_public_pair",
        "shot_reference_bindings",
        "(public_asset_link_id IS NULL) = (publication_item_id IS NULL)",
    )
    op.create_foreign_key(
        "fk_shot_reference_binding_public_link",
        "shot_reference_bindings",
        "project_public_asset_links",
        ["public_asset_link_id", "project_id"],
        ["id", "project_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_shot_reference_binding_resolution_mode",
        "shot_reference_bindings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_shot_reference_binding_resolution_mode",
        "shot_reference_bindings",
        "resolution_mode IN ('current_formal','pinned_version','direct_artifact','public_link')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_shot_reference_binding_resolution_mode",
        "shot_reference_bindings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_shot_reference_binding_resolution_mode",
        "shot_reference_bindings",
        "resolution_mode IN ('current_formal','pinned_version','direct_artifact')",
    )
    op.drop_constraint(
        "fk_shot_reference_binding_public_link",
        "shot_reference_bindings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_shot_reference_binding_public_pair",
        "shot_reference_bindings",
        type_="check",
    )
    op.drop_constraint(
        "ck_shot_reference_binding_source", "shot_reference_bindings", type_="check"
    )
    op.create_check_constraint(
        "ck_shot_reference_binding_source",
        "shot_reference_bindings",
        "asset_id IS NOT NULL OR asset_version_id IS NOT NULL OR artifact_id IS NOT NULL",
    )
    op.drop_column("shot_reference_bindings", "publication_item_id")
    op.drop_column("shot_reference_bindings", "public_asset_link_id")
    op.drop_constraint(
        "uq_public_link_project_scope", "project_public_asset_links", type_="unique"
    )
