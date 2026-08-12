"""Controlled Director workflow core.

Revision ID: 20260813_0018
Revises: 20260811_0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0018"
down_revision: str | None = "20260811_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _project_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_project_scope ON {table}
        FOR ALL
        USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
        """
    )


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
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
    )


def upgrade() -> None:
    op.execute("ALTER TYPE agent_operation ADD VALUE IF NOT EXISTS 'skill_execute'")
    created_at, updated_at = _timestamps()
    op.create_table(
        "director_workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", sa.String(80), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("current_stage", sa.String(32), nullable=False),
        sa.Column("current_artifact_versions", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        created_at,
        updated_at,
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", name="uq_director_workflow_project"),
    )

    op.create_table(
        "creative_artifact_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_kind", sa.String(48), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("supersedes_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id"],
            ["creative_artifact_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id",
            "artifact_kind",
            "revision_no",
            name="uq_creative_artifact_kind_revision",
        ),
        sa.UniqueConstraint(
            "project_id",
            "artifact_kind",
            "content_hash",
            name="uq_creative_artifact_kind_content",
        ),
    )

    op.create_table(
        "budget_authorizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authorization_kind", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("pricing_snapshot_id", sa.String(160), nullable=False),
        sa.Column("limit_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("consumed_amount", sa.Numeric(20, 6), server_default="0", nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column("authorized_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["authorized_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_budget_auth_idempotency"),
        sa.CheckConstraint("limit_amount > 0", name="ck_budget_auth_positive_limit"),
        sa.CheckConstraint(
            "consumed_amount >= 0 AND consumed_amount <= limit_amount",
            name="ck_budget_auth_consumed_range",
        ),
    )

    op.create_table(
        "approval_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_kind", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("approved_artifact_versions", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("budget_authorization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by_proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["budget_authorization_id"], ["budget_authorizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_approval_idempotency"),
    )

    op.create_table(
        "change_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("target_artifact_kind", sa.String(48), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("replacement_payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(32), server_default="awaiting_confirmation", nullable=False),
        sa.Column("proposed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"], ["creative_artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["proposed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_change_idempotency"),
    )
    op.create_foreign_key(
        "fk_approval_invalidating_proposal",
        "approval_records",
        "change_proposals",
        ["invalidated_by_proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "impact_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invalidated_version_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("affected_shot_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("reusable_artifact_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("estimated_added_cost", sa.Numeric(20, 6), nullable=True),
        sa.Column("estimated_added_time_seconds", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["change_proposal_id"], ["change_proposals.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("change_proposal_id", name="uq_impact_report_proposal"),
    )

    op.create_table(
        "workflow_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_key", sa.String(80), nullable=False),
        sa.Column("skill_id", sa.String(80), nullable=False),
        sa.Column("skill_version", sa.String(32), nullable=False),
        sa.Column("execution_kind", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("input_version_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("output_version_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_run_ref", sa.String(160), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["node_run_id"], ["node_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workflow_run_id", "idempotency_key", name="uq_step_run_idempotency"),
        sa.CheckConstraint(
            "num_nonnulls(agent_run_id, node_run_id, service_run_ref) <= 1",
            name="ck_step_run_single_execution_ref",
        ),
    )

    op.create_table(
        "director_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_type", sa.String(80), nullable=False),
        sa.Column("source_stage", sa.String(32), nullable=False),
        sa.Column("responsible_stage", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), server_default="open", nullable=False),
        sa.Column("evidence", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("suggested_actions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("affected_version_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("created_by_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"], ["workflow_step_runs.id"], ondelete="SET NULL"
        ),
    )

    op.create_table(
        "production_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_kind", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), server_default="planned", nullable=False),
        sa.Column("budget_authorization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locked_version_refs", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("selected_shot_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("template_keys", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("quality_policy_id", sa.String(100), nullable=False),
        sa.Column("selection_snapshot", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("semantic_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["director_workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["budget_authorization_id"],
            ["budget_authorizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_batch_idempotency"),
    )

    op.create_table(
        "production_batch_shots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_shot_id", sa.String(40), nullable=False),
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("graph_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), server_default="planned", nullable=False),
        sa.Column("semantic_hash", sa.CHAR(64), nullable=False),
        sa.Column("accepted_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_node_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["production_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["graph_version_id"], ["graph_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["accepted_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["accepted_node_run_id"], ["node_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("batch_id", "logical_shot_id", name="uq_batch_logical_shot"),
    )

    op.create_table(
        "budget_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authorization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("actual_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), server_default="reserved", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["production_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["authorization_id"], ["budget_authorizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["node_run_id"], ["node_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_budget_reservation_key"),
        sa.CheckConstraint("reserved_amount > 0", name="ck_budget_reservation_positive"),
        sa.CheckConstraint(
            "actual_amount IS NULL OR actual_amount >= 0",
            name="ck_budget_reservation_actual_nonnegative",
        ),
    )

    # Director-paid NodeRuns carry strong, queryable authorization lineage.
    # The columns remain nullable so historical non-Director runs keep their
    # existing execution semantics.
    op.add_column(
        "node_runs",
        sa.Column("production_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "node_runs",
        sa.Column("budget_reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_node_runs_production_batch",
        "node_runs",
        "production_batches",
        ["production_batch_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_node_runs_budget_reservation",
        "node_runs",
        "budget_reservations",
        ["budget_reservation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_node_runs_production_batch_id",
        "node_runs",
        ["production_batch_id"],
    )
    op.create_index(
        "ix_node_runs_budget_reservation_id",
        "node_runs",
        ["budget_reservation_id"],
    )

    for table in (
        "director_workflow_runs",
        "creative_artifact_versions",
        "budget_authorizations",
        "approval_records",
        "change_proposals",
        "impact_reports",
        "workflow_step_runs",
        "director_issues",
        "production_batches",
        "production_batch_shots",
        "budget_reservations",
    ):
        _project_rls(table)


def downgrade() -> None:
    op.drop_index("ix_node_runs_budget_reservation_id", table_name="node_runs")
    op.drop_index("ix_node_runs_production_batch_id", table_name="node_runs")
    op.drop_constraint(
        "fk_node_runs_budget_reservation", "node_runs", type_="foreignkey"
    )
    op.drop_constraint("fk_node_runs_production_batch", "node_runs", type_="foreignkey")
    op.drop_column("node_runs", "budget_reservation_id")
    op.drop_column("node_runs", "production_batch_id")
    for table in reversed(
        (
            "director_workflow_runs",
            "creative_artifact_versions",
            "budget_authorizations",
            "approval_records",
            "change_proposals",
            "impact_reports",
            "workflow_step_runs",
            "director_issues",
            "production_batches",
            "production_batch_shots",
            "budget_reservations",
        )
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
    op.drop_table("budget_reservations")
    op.drop_table("production_batch_shots")
    op.drop_table("production_batches")
    op.drop_table("director_issues")
    op.drop_table("workflow_step_runs")
    op.drop_table("impact_reports")
    op.drop_constraint("fk_approval_invalidating_proposal", "approval_records", type_="foreignkey")
    op.drop_table("change_proposals")
    op.drop_table("approval_records")
    op.drop_table("budget_authorizations")
    op.drop_table("creative_artifact_versions")
    op.drop_table("director_workflow_runs")
