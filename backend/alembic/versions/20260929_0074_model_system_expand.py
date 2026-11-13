"""Expand model truth without replacing any ProviderModelBinding.

This is Migration A only. Historical account_verified booleans do not become
positive availability evidence. Old catalog and binding columns remain for a
separate, gated runtime cutover and later cleanup release.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0074"
down_revision: str | None = "20260919_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKSPACE_TABLES = (
    "connection_discovered_models",
    "connection_model_capability_revisions",
    "provider_availability_evidence",
    "provider_model_availability",
)


def _workspace_scope(table: str, *, append_only: bool = False) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_workspace_scope ON {table} FOR ALL "
        "USING (workspace_id = app.current_workspace_id()) "
        "WITH CHECK (workspace_id = app.current_workspace_id())"
    )
    verbs = "SELECT, INSERT" if append_only else "SELECT, INSERT, UPDATE, DELETE"
    op.execute(f"GRANT {verbs} ON {table} TO dramaforge_app")
    if append_only:
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM dramaforge_app")


def _immutable_global(table: str) -> None:
    for role in ("dramaforge", "dramaforge_app"):
        op.execute(f"GRANT SELECT ON {table} TO {role}")
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM {role}")


def upgrade() -> None:
    op.create_table(
        "model_capability_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "legacy_catalog_entry_id",
            sa.UUID(),
            sa.ForeignKey("provider_model_catalog_entries.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("provider_type", sa.String(40), nullable=False),
        sa.Column("protocol_profile", sa.String(80), nullable=False),
        sa.Column("canonical_model_id", sa.String(160), nullable=False),
        sa.Column("model_revision", sa.String(120), nullable=False),
        sa.Column("media_kind", sa.String(20), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("source_snapshot_id", sa.String(120), nullable=True),
        sa.Column("documented_at", sa.Date(), nullable=True),
        sa.Column(
            "implementation_status",
            sa.String(24),
            nullable=False,
            server_default="manifest_mapped",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "provider_type",
            "protocol_profile",
            "canonical_model_id",
            "model_revision",
            name="uq_model_capability_identity",
        ),
        sa.UniqueConstraint("legacy_catalog_entry_id", name="uq_model_capability_legacy_catalog"),
        sa.CheckConstraint(
            "implementation_status IN ('not_implemented','manifest_mapped','contract_tested')",
            name="ck_model_capability_implementation_status",
        ),
    )
    op.create_table(
        "model_publication_states",
        sa.Column(
            "model_capability_revision_id",
            sa.UUID(),
            sa.ForeignKey("model_capability_revisions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("lifecycle", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "lifecycle IN ('active','legacy','deprecated','retired','unknown')",
            name="ck_model_publication_lifecycle",
        ),
    )
    op.create_table(
        "model_publication_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "model_capability_revision_id",
            sa.UUID(),
            sa.ForeignKey("model_capability_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_lifecycle", sa.String(20), nullable=True),
        sa.Column("to_lifecycle", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for table in (
        "model_capability_revisions",
        "model_publication_states",
        "model_publication_events",
    ):
        _immutable_global(table)

    op.create_table(
        "connection_discovered_models",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "connection_id",
            sa.UUID(),
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "connection_revision_id",
            sa.UUID(),
            sa.ForeignKey("provider_connection_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "credential_revision_id",
            sa.UUID(),
            sa.ForeignKey("encrypted_provider_credentials.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("remote_model_id", sa.String(240), nullable=False),
        sa.Column("protocol_contract_revision_id", sa.UUID(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "connection_revision_id",
            "credential_revision_id",
            "remote_model_id",
            name="uq_connection_discovered_model_identity",
        ),
    )
    op.create_table(
        "connection_model_capability_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "connection_discovered_model_id",
            sa.UUID(),
            sa.ForeignKey("connection_discovered_models.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("capability_revision", sa.String(80), nullable=False),
        sa.Column("capability_hash", sa.String(64), nullable=False),
        sa.Column("operations_json", sa.JSON(), nullable=False),
        sa.Column("input_contracts_json", sa.JSON(), nullable=False),
        sa.Column("parameter_constraints_json", sa.JSON(), nullable=False),
        sa.Column("protocol_contract_revision_id", sa.UUID(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "implementation_status",
            sa.String(24),
            nullable=False,
            server_default="not_implemented",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "connection_discovered_model_id",
            "capability_revision",
            name="uq_connection_model_capability_revision",
        ),
        sa.CheckConstraint(
            "implementation_status IN ('not_implemented','manifest_mapped','contract_tested')",
            name="ck_connection_model_implementation_status",
        ),
    )
    op.create_table(
        "provider_availability_evidence",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "connection_id",
            sa.UUID(),
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "connection_revision_id",
            sa.UUID(),
            sa.ForeignKey("provider_connection_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "credential_revision_id",
            sa.UUID(),
            sa.ForeignKey("encrypted_provider_credentials.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("remote_model_id", sa.String(240), nullable=False),
        sa.Column("verifier_kind", sa.String(60), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("listed_model_ids_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('visible','not_visible','auth_failed','forbidden',"
            "'region_unavailable','temporary_error','not_supported')",
            name="ck_provider_availability_evidence_status",
        ),
    )
    op.create_table(
        "provider_model_availability",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "connection_id",
            sa.UUID(),
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "connection_revision_id",
            sa.UUID(),
            sa.ForeignKey("provider_connection_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "credential_revision_id",
            sa.UUID(),
            sa.ForeignKey("encrypted_provider_credentials.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("remote_model_id", sa.String(240), nullable=False),
        sa.Column("effective_status", sa.String(32), nullable=False),
        sa.Column(
            "positive_evidence_id",
            sa.UUID(),
            sa.ForeignKey("provider_availability_evidence.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "latest_evidence_id",
            sa.UUID(),
            sa.ForeignKey("provider_availability_evidence.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "connection_revision_id",
            "credential_revision_id",
            "remote_model_id",
            name="uq_provider_model_availability_identity",
        ),
        sa.CheckConstraint(
            "effective_status IN ('visible','not_checked','not_visible','auth_failed',"
            "'forbidden','region_unavailable','not_supported')",
            name="ck_provider_model_availability_status",
        ),
    )
    for table in _WORKSPACE_TABLES:
        _workspace_scope(table, append_only=table != "provider_model_availability")

    op.add_column("provider_model_bindings", sa.Column("binding_target_kind", sa.String(24), nullable=True))
    op.add_column("provider_model_bindings", sa.Column("canonical_model_id", sa.String(160), nullable=True))
    op.add_column(
        "provider_model_bindings", sa.Column("model_capability_revision_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "provider_model_bindings", sa.Column("connection_discovered_model_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "provider_model_bindings",
        sa.Column("connection_model_capability_revision_id", sa.UUID(), nullable=True),
    )
    for column, table, constraint in (
        ("model_capability_revision_id", "model_capability_revisions", "fk_pmb_model_revision"),
        ("connection_discovered_model_id", "connection_discovered_models", "fk_pmb_discovered_model"),
        (
            "connection_model_capability_revision_id",
            "connection_model_capability_revisions",
            "fk_pmb_connection_capability",
        ),
    ):
        op.create_foreign_key(
            constraint,
            "provider_model_bindings",
            table,
            [column],
            ["id"],
            ondelete="RESTRICT",
        )

    # Keep the original catalog as rollback data. Only official concrete models
    # are mapped; protocol contracts are never promoted to Global model truth.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, provider_type, protocol_profile, model_id, model_revision, "
            "media_kind, capability_manifest_json, documented_at "
            "FROM provider_model_catalog_entries "
            "WHERE catalog_source = 'official_static'"
        )
    ).mappings()
    for row in rows:
        manifest = dict(row["capability_manifest_json"])
        manifest.pop("lifecycle", None)
        manifest.pop("catalog_source", None)
        manifest_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        bind.execute(
            sa.text(
                "INSERT INTO model_capability_revisions "
                "(id, legacy_catalog_entry_id, provider_type, protocol_profile, "
                "canonical_model_id, model_revision, media_kind, manifest_json, "
                "manifest_hash, documented_at, implementation_status) "
                "VALUES (:id, :id, :provider_type, :protocol_profile, :canonical_model_id, "
                ":model_revision, :media_kind, CAST(:manifest_json AS json), :manifest_hash, "
                ":documented_at, 'manifest_mapped')"
            ),
            {
                "id": row["id"],
                "provider_type": row["provider_type"],
                "protocol_profile": row["protocol_profile"],
                "canonical_model_id": row["model_id"],
                "model_revision": row["model_revision"],
                "media_kind": row["media_kind"],
                "manifest_json": json.dumps(manifest, sort_keys=True, default=str),
                "manifest_hash": manifest_hash,
                "documented_at": row["documented_at"],
            },
        )
        # The old mutable lifecycle is not official current-state evidence.
        # Source review must publish active/legacy/deprecated explicitly later.
        lifecycle = "unknown"
        bind.execute(
            sa.text(
                "INSERT INTO model_publication_states "
                "(model_capability_revision_id, lifecycle) VALUES (:id, :lifecycle)"
            ),
            {"id": row["id"], "lifecycle": lifecycle},
        )
        bind.execute(
            sa.text(
                "INSERT INTO model_publication_events "
                "(id, model_capability_revision_id, from_lifecycle, to_lifecycle, reason) "
                "VALUES (:event_id, :id, NULL, :lifecycle, 'migration_a_unreviewed_catalog_import')"
            ),
            {"event_id": uuid4(), "id": row["id"], "lifecycle": lifecycle},
        )

    bind.execute(
        sa.text(
            "UPDATE provider_model_bindings AS b "
            "SET binding_target_kind = 'global_model', "
            "model_capability_revision_id = m.id, "
            "canonical_model_id = m.canonical_model_id "
            "FROM model_capability_revisions AS m "
            "WHERE b.catalog_entry_id = m.legacy_catalog_entry_id"
        )
    )
    op.create_check_constraint(
        "ck_provider_model_binding_target",
        "provider_model_bindings",
        "(binding_target_kind IS NULL AND canonical_model_id IS NULL "
        "AND model_capability_revision_id IS NULL "
        "AND connection_discovered_model_id IS NULL "
        "AND connection_model_capability_revision_id IS NULL) OR "
        "(binding_target_kind = 'global_model' AND model_capability_revision_id IS NOT NULL "
        "AND canonical_model_id IS NOT NULL AND connection_discovered_model_id IS NULL "
        "AND connection_model_capability_revision_id IS NULL) OR "
        "(binding_target_kind = 'connection_model' AND model_capability_revision_id IS NULL "
        "AND canonical_model_id IS NULL AND connection_discovered_model_id IS NOT NULL "
        "AND connection_model_capability_revision_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_provider_model_binding_target", "provider_model_bindings", type_="check")
    for column, constraint in (
        ("connection_model_capability_revision_id", "fk_pmb_connection_capability"),
        ("connection_discovered_model_id", "fk_pmb_discovered_model"),
        ("model_capability_revision_id", "fk_pmb_model_revision"),
    ):
        op.drop_constraint(constraint, "provider_model_bindings", type_="foreignkey")
        op.drop_column("provider_model_bindings", column)
    op.drop_column("provider_model_bindings", "canonical_model_id")
    op.drop_column("provider_model_bindings", "binding_target_kind")
    for table in reversed(_WORKSPACE_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_scope ON {table}")
        op.drop_table(table)
    for table in (
        "model_publication_events",
        "model_publication_states",
        "model_capability_revisions",
    ):
        op.drop_table(table)
