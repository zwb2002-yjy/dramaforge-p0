"""S1-DB-0.1: graph_nodes/edges, node_runs, artifacts, provider_ops, briefs/plans.

Revision ID: 20260721_0004
Revises: 20260720_0003

Field-faithful to 04 for tables required by the first product vertical slice.
Does not claim S2 Gate complete.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0004"
down_revision: Union[str, None] = "20260720_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    e = postgresql.ENUM(*values, name=name, create_type=False)
    e.create(op.get_bind(), checkfirst=True)
    return e


def upgrade() -> None:
    creation_plan_status = _enum(
        "creation_plan_status",
        "draft",
        "awaiting_confirmation",
        "confirmed",
        "superseded",
        "cancelled",
    )
    creative_revision_source = _enum(
        "creative_revision_source", "user", "agent", "imported"
    )
    agent_operation = _enum(
        "agent_operation", "draft_brief", "refine_brief", "draft_plan"
    )
    agent_run_status = _enum(
        "agent_run_status",
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "stale",
        "cancelled",
    )
    provider_operation_purpose = _enum(
        "provider_operation_purpose",
        "primary",
        "schema_repair",
        "transport_retry",
        "provider_fallback",
    )
    materialization_operation_status = _enum(
        "materialization_operation_status", "pending", "completed", "failed"
    )
    node_type = _enum(
        "node_type",
        "prompt_compose",
        "keyframe",
        "face_review",
        "video",
        "video_review",
        "voice",
        "subtitle",
        "composite",
        "continuity_review",
        "export",
    )
    node_run_status = _enum(
        "node_run_status",
        "queued",
        "running",
        "cancel_requested",
        "cached",
        "blocked_budget",
        "completed",
        "completed_after_cancel",
        "failed",
        "cancelled",
    )
    provider_operation_status = _enum(
        "provider_operation_status",
        "created",
        "submitted",
        "running",
        "cancel_requested",
        "cancelled",
        "succeeded",
        "failed",
        "timed_out",
    )
    artifact_type = _enum(
        "artifact_type",
        "image",
        "video",
        "audio",
        "subtitle",
        "timeline",
        "export_package",
        "document",
    )
    artifact_state = _enum(
        "artifact_state",
        "quarantined",
        "available",
        "cold",
        "delete_requested",
        "deleted",
    )

    # --- Creation (start_project + manual brief/plan) ---
    op.create_table(
        "creative_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("version > 0"),
    )
    op.create_index("idx_creative_briefs_project", "creative_briefs", ["project_id", sa.text("updated_at DESC")])

    op.create_table(
        "creative_brief_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("creative_brief_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("supersedes_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_kind", creative_revision_source, nullable=False),
        sa.Column("source_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("brief", postgresql.JSONB(), nullable=False),
        sa.Column("status", creation_plan_status, server_default="draft", nullable=False),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["creative_brief_id"], ["creative_briefs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_revision_id"],
            ["creative_brief_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("creative_brief_id", "revision_no"),
        sa.UniqueConstraint("id", "project_id"),
        sa.CheckConstraint("revision_no > 0"),
        sa.CheckConstraint("(source_kind = 'agent') = (source_agent_run_id IS NOT NULL)"),
        sa.CheckConstraint(
            "(status = 'confirmed') = (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)"
        ),
    )
    op.create_index(
        "idx_brief_revisions_project_status",
        "creative_brief_revisions",
        ["project_id", "status", sa.text("created_at DESC")],
    )

    op.execute(
        """
        ALTER TABLE creative_briefs
        ADD CONSTRAINT fk_creative_briefs_current_revision
        FOREIGN KEY (current_revision_id) REFERENCES creative_brief_revisions(id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        """
    )

    op.create_table(
        "creation_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_brief_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column("context_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "materialization_schema_version",
            sa.String(40),
            server_default="materialization-p0-v1",
            nullable=False,
        ),
        sa.Column("status", creation_plan_status, server_default="draft", nullable=False),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_brief_revision_id"],
            ["creative_brief_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("version > 0"),
        sa.CheckConstraint("materialization_schema_version = 'materialization-p0-v1'"),
        sa.CheckConstraint(
            "(status = 'confirmed') = (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)"
        ),
    )
    op.create_index(
        "idx_creation_plans_project_status",
        "creation_plans",
        ["project_id", "status", sa.text("updated_at DESC")],
    )

    op.create_table(
        "planning_authorizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pricing_snapshot_id", sa.String(120), nullable=False),
        sa.Column("authorized_operations", postgresql.ARRAY(agent_operation), nullable=False),
        sa.Column("estimated_max_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.CHAR(3), server_default="USD", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("estimated_max_amount > 0"),
        sa.CheckConstraint("cardinality(authorized_operations) > 0"),
        sa.CheckConstraint("expires_at > created_at"),
    )
    op.create_index(
        "idx_planning_authorizations_project_expiry",
        "planning_authorizations",
        ["project_id", "expires_at"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planning_authorization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", agent_operation, nullable=False),
        sa.Column("status", agent_run_status, server_default="queued", nullable=False),
        sa.Column("target_brief_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_capability", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("output_schema_version", sa.String(80), nullable=False),
        sa.Column("context_compiler_version", sa.String(80), nullable=False),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("context_hash", sa.CHAR(64), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_request_id", sa.String(160), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(120), nullable=True),
        sa.Column("claim_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("stable_error_code", sa.String(100), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("result_brief_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["planning_authorization_id"],
            ["planning_authorizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_brief_revision_id"],
            ["creative_brief_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["target_plan_id"], ["creation_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["result_brief_revision_id"],
            ["creative_brief_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["result_plan_id"], ["creation_plans.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("planning_authorization_id"),
        sa.CheckConstraint("claim_count >= 0"),
        sa.CheckConstraint("dispatch_generation > 0"),
        sa.CheckConstraint("version > 0"),
    )
    op.create_index(
        "idx_agent_runs_claim",
        "agent_runs",
        ["status", "next_attempt_at", "leased_until"],
        postgresql_where=sa.text(
            "status IN ('queued','running','cancel_requested')"
        ),
    )

    op.execute(
        """
        ALTER TABLE creative_brief_revisions
        ADD CONSTRAINT fk_brief_revision_source_agent_run
        FOREIGN KEY (source_agent_run_id) REFERENCES agent_runs(id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        ALTER TABLE creation_plans
        ADD CONSTRAINT fk_creation_plan_source_agent_run
        FOREIGN KEY (source_agent_run_id) REFERENCES agent_runs(id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        """
    )

    op.create_table(
        "materialization_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creation_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_key", sa.String(120), nullable=False),
        sa.Column("operation_kind", sa.String(80), nullable=False),
        sa.Column("payload_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "status",
            materialization_operation_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("result_entity_type", sa.String(80), nullable=True),
        sa.Column("result_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creation_plan_id"], ["creation_plans.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("creation_plan_id", "operation_key"),
        sa.CheckConstraint(
            "(status = 'completed') = (result_entity_type IS NOT NULL AND result_entity_id IS NOT NULL)"
        ),
    )
    op.create_index(
        "idx_materialization_operations_project_plan",
        "materialization_operations",
        ["project_id", "creation_plan_id", "status"],
    )

    # --- Execution graph layer ---
    op.create_table(
        "graph_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("graph_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_key", sa.String(120), nullable=False),
        sa.Column("node_type", node_type, nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("input_schema", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("output_schema", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("cacheable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("latest_successful_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["graph_version_id"], ["graph_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("graph_version_id", "node_key", name="uq_graph_nodes_version_key"),
    )

    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("graph_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upstream_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("output_port", sa.String(80), nullable=False),
        sa.Column("downstream_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_port", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["graph_version_id"], ["graph_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upstream_node_id"], ["graph_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["downstream_node_id"], ["graph_nodes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "graph_version_id",
            "upstream_node_id",
            "output_port",
            "downstream_node_id",
            "input_port",
            "position",
        ),
        sa.UniqueConstraint(
            "graph_version_id", "downstream_node_id", "input_port", "position"
        ),
        sa.CheckConstraint("position >= 0"),
        sa.CheckConstraint("upstream_node_id <> downstream_node_id"),
    )
    op.create_index(
        "idx_graph_edges_downstream",
        "graph_edges",
        ["graph_version_id", "downstream_node_id", "input_port", "position"],
    )

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", artifact_type, nullable=False),
        sa.Column("storage_state", artifact_state, server_default="quarantined", nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(10, 3), nullable=True),
        sa.Column("produced_by_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_reason", sa.String(240), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            "artifact_type",
            name="uq_artifacts_project_hash_type",
        ),
        sa.CheckConstraint("byte_size >= 0"),
        sa.CheckConstraint("width IS NULL OR width > 0"),
        sa.CheckConstraint("height IS NULL OR height > 0"),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0"),
    )
    op.create_index(
        "idx_artifacts_project_state", "artifacts", ["project_id", "storage_state"]
    )

    op.create_table(
        "node_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("status", node_run_status, server_default="queued", nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("output_summary", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_cost", sa.Numeric(20, 6), server_default="0", nullable=False),
        sa.Column("platform_cost", sa.Numeric(20, 6), server_default="0", nullable=False),
        sa.Column("avoided_cost_estimate", sa.Numeric(20, 6), server_default="0", nullable=False),
        sa.Column("result_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reused_from_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["graph_version_id"], ["graph_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["graph_node_id"], ["graph_nodes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_run_id"], ["node_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reused_from_run_id"], ["node_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_node_runs_idempotency"),
        sa.UniqueConstraint("graph_node_id", "attempt_no"),
        sa.CheckConstraint("attempt_no > 0"),
        sa.CheckConstraint("provider_cost >= 0"),
        sa.CheckConstraint("platform_cost >= 0"),
        sa.CheckConstraint("avoided_cost_estimate >= 0"),
        sa.CheckConstraint("(status <> 'cached') OR reused_from_run_id IS NOT NULL"),
        sa.CheckConstraint(
            "(status NOT IN ('completed','cached','completed_after_cancel')) OR result_artifact_id IS NOT NULL"
        ),
        sa.CheckConstraint(
            "(status <> 'cached') OR (provider_cost = 0 AND platform_cost = 0)"
        ),
    )
    op.create_index(
        "idx_node_runs_cache_lookup",
        "node_runs",
        ["project_id", "graph_node_id", "input_hash", "status", sa.text("finished_at DESC")],
    )
    op.create_index(
        "idx_node_runs_reused_from",
        "node_runs",
        ["reused_from_run_id"],
        postgresql_where=sa.text("reused_from_run_id IS NOT NULL"),
    )

    op.execute(
        """
        ALTER TABLE graph_nodes
        ADD CONSTRAINT fk_graph_nodes_latest_successful_run
        FOREIGN KEY (latest_successful_run_id) REFERENCES node_runs(id)
        ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        ALTER TABLE artifacts
        ADD CONSTRAINT fk_artifacts_produced_by_run
        FOREIGN KEY (produced_by_run_id) REFERENCES node_runs(id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        ALTER TABLE node_runs
        ADD CONSTRAINT fk_node_runs_result_artifact
        FOREIGN KEY (result_artifact_id) REFERENCES artifacts(id)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        """
    )

    op.create_table(
        "provider_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "purpose",
            provider_operation_purpose,
            server_default="primary",
            nullable=False,
        ),
        sa.Column("operation_kind", sa.String(80), nullable=False),
        sa.Column("actual_provider", sa.String(64), nullable=False),
        sa.Column("actual_model", sa.String(120), nullable=False),
        sa.Column("provider_operation_id", sa.String(200), nullable=True),
        sa.Column("request_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column(
            "status",
            provider_operation_status,
            server_default="created",
            nullable=False,
        ),
        sa.Column("request_summary", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("response_summary", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_cost", sa.Numeric(20, 6), nullable=True),
        sa.Column("currency", sa.CHAR(3), server_default="USD", nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["node_run_id"], ["node_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint("attempt_no > 0"),
        sa.CheckConstraint("(node_run_id IS NOT NULL) <> (agent_run_id IS NOT NULL)"),
    )
    op.create_index(
        "uq_provider_operations_node_run",
        "provider_operations",
        ["node_run_id"],
        unique=True,
        postgresql_where=sa.text("node_run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_provider_operations_agent_attempt",
        "provider_operations",
        ["agent_run_id", "attempt_no"],
        unique=True,
        postgresql_where=sa.text("agent_run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_provider_operations_remote",
        "provider_operations",
        ["actual_provider", "provider_operation_id"],
        unique=True,
        postgresql_where=sa.text("provider_operation_id IS NOT NULL"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.reject_provider_operation_for_cached_run()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.node_run_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM node_runs WHERE id = NEW.node_run_id AND status = 'cached'
          ) THEN
            RAISE EXCEPTION 'cached node run cannot create provider operation';
          END IF;
          RETURN NEW;
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_provider_operation_reject_cached
        BEFORE INSERT OR UPDATE OF node_run_id ON provider_operations
        FOR EACH ROW EXECUTE FUNCTION app.reject_provider_operation_for_cached_run()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_provider_operation_reject_cached ON provider_operations")
    op.execute("DROP FUNCTION IF EXISTS app.reject_provider_operation_for_cached_run()")
    op.drop_table("provider_operations")
    op.execute("ALTER TABLE node_runs DROP CONSTRAINT IF EXISTS fk_node_runs_result_artifact")
    op.execute("ALTER TABLE artifacts DROP CONSTRAINT IF EXISTS fk_artifacts_produced_by_run")
    op.execute("ALTER TABLE graph_nodes DROP CONSTRAINT IF EXISTS fk_graph_nodes_latest_successful_run")
    op.drop_table("node_runs")
    op.drop_table("artifacts")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("materialization_operations")
    op.execute("ALTER TABLE creation_plans DROP CONSTRAINT IF EXISTS fk_creation_plan_source_agent_run")
    op.execute(
        "ALTER TABLE creative_brief_revisions DROP CONSTRAINT IF EXISTS fk_brief_revision_source_agent_run"
    )
    op.drop_table("agent_runs")
    op.drop_table("planning_authorizations")
    op.drop_table("creation_plans")
    op.execute(
        "ALTER TABLE creative_briefs DROP CONSTRAINT IF EXISTS fk_creative_briefs_current_revision"
    )
    op.drop_table("creative_brief_revisions")
    op.drop_table("creative_briefs")
