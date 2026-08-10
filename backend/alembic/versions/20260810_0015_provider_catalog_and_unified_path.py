"""Provider model catalog + binding/evidence/operation extensions.

Revision ID: 20260810_0015
Revises: 20260803_0014

Stage A+B: immutable model catalog (global, read-only, versioned), binding-level
probe/evidence fields, and unified-execution audit fields on ProviderOperation.
Seeds are inserted from the FROZEN snapshot ``_seeds_0015.py`` (never from
current runtime code), so replaying this migration is stable across time.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Sequence
from datetime import date as _date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0015"
down_revision: str | None = "20260803_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_ROLES = ("dramaforge", "dramaforge_app")


def _frozen_seeds() -> tuple[list[dict], object]:
    """Load the frozen seed snapshot as a module without importing runtime code.

    The snapshot lives in ``alembic/_seeds_0015.py`` (outside ``versions/`` so
    Alembic never scans it as a migration).
    """
    here = os.path.dirname(__file__)
    path = os.path.join(here, "..", "_seeds_0015.py")
    spec = importlib.util.spec_from_file_location("_seeds_0015", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FROZEN_0015, module


def _create_catalog_table() -> None:
    op.create_table(
        "provider_model_catalog_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_type", sa.String(40), nullable=False),
        sa.Column("protocol_profile", sa.String(80), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("model_revision", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("media_kind", sa.String(20), nullable=False),
        sa.Column("lifecycle", sa.String(20), server_default="active", nullable=False),
        sa.Column(
            "catalog_source", sa.String(32), server_default="official_static", nullable=False
        ),
        sa.Column("capability_manifest_json", sa.JSON(), nullable=False),
        sa.Column("option_schema_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("pricing_snapshot_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("documented_at", sa.Date(), nullable=True),
        sa.Column("contract_manifest_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "provider_type",
            "protocol_profile",
            "model_id",
            "model_revision",
            name="uq_provider_catalog_entry_revision",
        ),
    )
    # Global, non-sensitive, read-only for the application. No workspace RLS.
    for role in _CATALOG_ROLES:
        op.execute(f"GRANT SELECT ON provider_model_catalog_entries TO {role}")
        op.execute(
            "REVOKE INSERT, UPDATE, DELETE ON provider_model_catalog_entries "
            f"FROM {role}"
        )


def _seed_catalog() -> None:
    seeds, module = _frozen_seeds()
    bind = op.get_bind()
    for manifest in seeds:
        manifest_hash = module.hash_seed(manifest)
        option_schema = manifest.get("option_schema") or {"namespace": "", "options": {}}
        documented_at = manifest.get("documented_at")
        bind.execute(
            sa.text(
                """
                INSERT INTO provider_model_catalog_entries
                  (id, provider_type, protocol_profile, model_id, model_revision,
                   display_name, media_kind, lifecycle, catalog_source,
                   capability_manifest_json, option_schema_json, pricing_snapshot_json,
                   documented_at, contract_manifest_hash, created_at, updated_at)
                VALUES
                  (:id, :provider_type, :protocol_profile, :model_id, :model_revision,
                   :display_name, :media_kind, :lifecycle, :catalog_source,
                   CAST(:manifest AS json), CAST(:option_schema AS json),
                   CAST('{}' AS json), :documented_at,
                   :manifest_hash, now(), now())
                ON CONFLICT (provider_type, protocol_profile, model_id, model_revision)
                DO NOTHING
                """
            ),
            {
                "id": uuid4(),
                "provider_type": manifest["provider_type"],
                "protocol_profile": manifest["protocol_profile"],
                "model_id": manifest["model_id"],
                "model_revision": manifest["model_revision"],
                "display_name": manifest["display_name"],
                "media_kind": manifest["media_kind"],
                "lifecycle": manifest.get("lifecycle", "active"),
                "catalog_source": manifest.get("catalog_source", "official_static"),
                "manifest": json.dumps(manifest),
                "option_schema": json.dumps(option_schema),
                "documented_at": (
                    _date.fromisoformat(documented_at) if documented_at else None
                ),
                "manifest_hash": manifest_hash,
            },
        )


def _extend_bindings() -> None:
    op.add_column(
        "provider_model_bindings",
        sa.Column("catalog_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "provider_model_bindings",
        sa.Column("capability_manifest_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "provider_model_bindings",
        sa.Column("remote_resource_kind", sa.String(20), nullable=True),
    )
    op.add_column(
        "provider_model_bindings",
        sa.Column("remote_resource_id", sa.String(240), nullable=True),
    )
    op.add_column(
        "provider_model_bindings",
        sa.Column("invoke_model_value", sa.String(160), nullable=True),
    )
    op.create_index(
        "ix_provider_model_bindings_catalog_entry_id",
        "provider_model_bindings",
        ["catalog_entry_id"],
    )
    op.create_foreign_key(
        "fk_provider_model_bindings_catalog_entry",
        "provider_model_bindings",
        "provider_model_catalog_entries",
        ["catalog_entry_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def _extend_capability_evidence() -> None:
    op.add_column(
        "provider_capability_evidence",
        sa.Column("model_binding_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "provider_capability_evidence",
        sa.Column("capability_manifest_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "provider_capability_evidence",
        sa.Column("credential_revision", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_provider_capability_evidence_model_binding_id",
        "provider_capability_evidence",
        ["model_binding_id"],
    )
    op.create_foreign_key(
        "fk_provider_capability_evidence_model_binding",
        "provider_capability_evidence",
        "provider_model_bindings",
        ["model_binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def _extend_project_bindings() -> None:
    op.add_column(
        "project_provider_bindings",
        sa.Column(
            "selection_strategy",
            sa.String(32),
            server_default="explicit_binding",
            nullable=False,
        ),
    )


def _extend_operations() -> None:
    op.add_column(
        "provider_operations",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "provider_operations",
        sa.Column("model_binding_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "provider_operations",
        sa.Column("catalog_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "provider_operations",
        sa.Column("capability_manifest_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "provider_operations",
        sa.Column("selection_plan", sa.JSON(), nullable=True),
    )
    op.add_column(
        "provider_operations",
        sa.Column("resume_token", sa.JSON(), nullable=True),
    )
    op.add_column(
        "provider_operations",
        sa.Column("execution_path_version", sa.String(32), nullable=True),
    )
    for index_name, column in (
        ("ix_provider_operations_connection_id", "connection_id"),
        ("ix_provider_operations_model_binding_id", "model_binding_id"),
        ("ix_provider_operations_catalog_entry_id", "catalog_entry_id"),
    ):
        op.create_index(index_name, "provider_operations", [column])
    op.create_foreign_key(
        "fk_provider_operations_connection",
        "provider_operations",
        "provider_connections",
        ["connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_provider_operations_model_binding",
        "provider_operations",
        "provider_model_bindings",
        ["model_binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_provider_operations_catalog_entry",
        "provider_operations",
        "provider_model_catalog_entries",
        ["catalog_entry_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        "ALTER TYPE provider_operation_status ADD VALUE IF NOT EXISTS 'submission_started'"
    )
    op.execute("ALTER TYPE provider_operation_status ADD VALUE IF NOT EXISTS 'rejected'")


def _backfill_model_bindings() -> None:
    # Idempotent backfill of existing bindings to the active catalog revision.
    # Only the extension columns are written; documented/contract_tested/
    # account_verified/quality_gated are untouched so old projects keep their
    # pre-migration verification state and gain no unverified capability.
    op.execute(
        """
        UPDATE provider_model_bindings b
        SET catalog_entry_id = c.id,
            capability_manifest_hash = c.contract_manifest_hash,
            remote_resource_kind = 'model',
            remote_resource_id = b.model_id,
            invoke_model_value = b.model_id
        FROM provider_connections conn, provider_model_catalog_entries c
        WHERE b.connection_id = conn.id
          AND c.provider_type = conn.provider_type
          AND c.protocol_profile = conn.protocol_profile
          AND c.model_id = b.model_id
          AND c.lifecycle = 'active'
          AND b.catalog_entry_id IS NULL
        """
    )


def upgrade() -> None:
    _create_catalog_table()
    _seed_catalog()
    _extend_bindings()
    _extend_capability_evidence()
    _extend_project_bindings()
    _extend_operations()
    _backfill_model_bindings()


def downgrade() -> None:
    for index_name in (
        "ix_provider_operations_connection_id",
        "ix_provider_operations_model_binding_id",
        "ix_provider_operations_catalog_entry_id",
    ):
        op.drop_index(index_name, table_name="provider_operations")
    for column in (
        "connection_id",
        "model_binding_id",
        "catalog_entry_id",
        "capability_manifest_hash",
        "selection_plan",
        "resume_token",
        "execution_path_version",
    ):
        op.drop_column("provider_operations", column)

    op.drop_index(
        "ix_provider_capability_evidence_model_binding_id",
        table_name="provider_capability_evidence",
    )
    for column in ("model_binding_id", "capability_manifest_hash", "credential_revision"):
        op.drop_column("provider_capability_evidence", column)

    op.drop_index(
        "ix_provider_model_bindings_catalog_entry_id",
        table_name="provider_model_bindings",
    )
    for column in (
        "catalog_entry_id",
        "capability_manifest_hash",
        "remote_resource_kind",
        "remote_resource_id",
        "invoke_model_value",
    ):
        op.drop_column("provider_model_bindings", column)

    op.drop_column("project_provider_bindings", "selection_strategy")
    op.drop_table("provider_model_catalog_entries")
