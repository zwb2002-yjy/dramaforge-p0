"""Provider connections, evidence/bindings, and artifact reference delivery.

Revision ID: 20260803_0014
Revises: 20260730_0013
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_0014"
down_revision: str | None = "20260730_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _workspace_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_workspace_scope ON {table}
        FOR ALL
        USING (
          workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = {table}.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
        )
        WITH CHECK (
          workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = {table}.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
        )
        """
    )


def upgrade() -> None:
    op.add_column(
        "provider_operations",
        sa.Column("remote_secondary_id", sa.String(200), nullable=True),
    )
    op.add_column(
        "provider_operations",
        sa.Column("protocol_profile", sa.String(80), nullable=True),
    )
    op.execute("ALTER TYPE provider_operation_status ADD VALUE IF NOT EXISTS 'unknown_submission'")

    op.create_table(
        "provider_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_type", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(240), nullable=False),
        sa.Column("protocol_profile", sa.String(80), nullable=False),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "verification_status", sa.String(40), server_default="unverified", nullable=False
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["encrypted_provider_credentials.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider_type",
            "protocol_profile",
            name="uq_provider_connection_profile",
        ),
    )
    op.create_table(
        "provider_capability_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(60), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("evidence_level", sa.String(40), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(200), nullable=True),
        sa.Column("reference_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("remote_query_kind", sa.String(20), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "budget_authorized",
            sa.Numeric(20, 6),
            server_default="0",
            nullable=False,
        ),
        sa.Column("provider_cost", sa.Numeric(20, 6), nullable=True),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column(
            "cost_status",
            sa.String(32),
            server_default="not_reported",
            nullable=False,
        ),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column(
            "tested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["provider_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "provider_model_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("documented", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("contract_tested", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("account_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("quality_gated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["provider_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "connection_id", "media_type", "model_id", "purpose", name="uq_provider_model_binding"
        ),
    )
    op.create_table(
        "project_provider_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("model_binding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fallback_policy", sa.String(20), server_default="none", nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["model_binding_id"], ["provider_model_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "purpose", name="uq_project_provider_binding"),
    )
    op.create_table(
        "provider_quality_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_binding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_kind", sa.String(40), nullable=False),
        sa.Column("policy_id", sa.String(100), nullable=False),
        sa.Column("score", sa.Numeric(10, 6), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["model_binding_id"], ["provider_model_bindings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["node_run_id"], ["node_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "model_binding_id",
            "node_run_id",
            name="uq_provider_quality_evidence_run",
        ),
    )
    op.create_table(
        "artifact_reference_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_run_id"], ["node_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(created_by_run_id IS NOT NULL) <> (created_by_user_id IS NOT NULL)",
            name="ck_artifact_reference_token_creator",
        ),
        sa.UniqueConstraint("token_hash", name="uq_artifact_reference_token_hash"),
    )

    for table in (
        "provider_connections",
        "provider_capability_evidence",
        "provider_model_bindings",
        "project_provider_bindings",
        "provider_quality_evidence",
        "artifact_reference_tokens",
    ):
        _workspace_rls(table)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.artifact_reference_for_token(p_token_hash text)
        RETURNS TABLE(artifact_id uuid, project_id uuid, object_key text, mime_type varchar,
                      content_hash varchar, expires_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT a.id, a.project_id, a.object_key, a.mime_type,
                 a.content_hash::varchar, t.expires_at
          FROM artifact_reference_tokens t
          JOIN artifacts a ON a.id = t.artifact_id
          WHERE t.token_hash = p_token_hash
            AND t.expires_at > now()
            AND a.storage_state = 'available'
            AND a.deleted_at IS NULL
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.artifact_reference_for_token(text) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.artifact_reference_for_token(text) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.artifact_reference_for_token(text)")
    for table in (
        "artifact_reference_tokens",
        "project_provider_bindings",
        "provider_quality_evidence",
        "provider_model_bindings",
        "provider_capability_evidence",
        "provider_connections",
    ):
        op.drop_table(table)
    op.drop_column("provider_operations", "protocol_profile")
    op.drop_column("provider_operations", "remote_secondary_id")
