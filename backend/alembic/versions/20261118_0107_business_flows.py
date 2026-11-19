"""Persist BusinessFlow instances, steps and attempts (I6a-01).

Three project-scoped tables plus the Turn link to a flow attempt. The tables
carry only coordination facts; media/production truth stays in NodeRun,
ProviderOperation and Artifact. A partial unique index keeps at most one active
attempt per step, and ``unknown_submission`` or an unresolved external effect
still occupies that slot.

Revision ID: 20261118_0107
Revises: 20261118_0106
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261118_0107"
down_revision: str | None = "20261118_0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INSTANCE_STATUSES = (
    "pending", "running", "waiting", "paused", "succeeded", "failed", "cancelled",
)
STEP_STATUSES = (
    "pending", "ready", "running", "waiting_user", "waiting_execution", "blocked",
    "succeeded", "failed", "skipped", "cancelled", "superseded",
)
ATTEMPT_STATUSES = (
    "pending", "running", "waiting_user", "waiting_execution", "unknown_submission",
    "succeeded", "failed", "cancelled",
)
ACTION_KINDS = ("read", "proposal", "apply", "production", "repair", "review")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({','.join(repr(value) for value in values)})"


def upgrade() -> None:
    # Parent candidate keys required by the attempt's receipt references.
    op.create_unique_constraint("uq_node_run_scope", "node_runs", ["id", "project_id"])
    op.create_unique_constraint(
        "uq_command_auth_scope", "production_command_authorizations", ["id", "project_id"]
    )

    op.create_table(
        "director_business_flow_instances",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("supervisor_run_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("flow_key", sa.String(120), nullable=False),
        sa.Column("definition_key", sa.String(120), nullable=False),
        sa.Column("definition_version", sa.String(80), nullable=False),
        sa.Column("contract_hash", sa.CHAR(64), nullable=False),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("input_data", postgresql.JSONB(), nullable=False),
        sa.Column("scope_type", sa.String(24), nullable=False),
        sa.Column("scope_entity_id", sa.UUID(), nullable=False),
        sa.Column("created_by_turn_id", sa.UUID(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("wait_reason", sa.String(80), nullable=True),
        sa.Column("terminal_reason", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "supervisor_run_id", "plan_id", "flow_key", name="uq_flow_instance_run_plan_flow"
        ),
        sa.UniqueConstraint(
            "id", "supervisor_run_id", "plan_id", "plan_revision", "project_id",
            name="uq_flow_instance_plan_identity",
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_run_id", "project_id"],
            ["director_master_runs.id", "director_master_runs.project_id"],
            ondelete="NO ACTION", name="fk_flow_instance_run",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "plan_revision", "supervisor_run_id", "project_id"],
            [
                "director_master_run_plans.id",
                "director_master_run_plans.revision",
                "director_master_run_plans.master_run_id",
                "director_master_run_plans.project_id",
            ],
            ondelete="NO ACTION", name="fk_flow_instance_plan",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_turn_id", "supervisor_run_id", "plan_revision", "project_id"],
            [
                "director_turns.id",
                "director_turns.master_run_id",
                "director_turns.plan_revision",
                "director_turns.project_id",
            ],
            ondelete="NO ACTION", name="fk_flow_instance_turn",
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint("revision > 0", name="ck_flow_instance_revision"),
        sa.CheckConstraint("plan_revision > 0", name="ck_flow_instance_plan_revision"),
        sa.CheckConstraint(_in("status", INSTANCE_STATUSES), name="ck_flow_instance_status"),
        sa.CheckConstraint(
            "scope_type IN ('project','scene','shot')", name="ck_flow_instance_scope"
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded','failed','cancelled')) = (finished_at IS NOT NULL)",
            name="ck_flow_instance_finished",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded','failed','cancelled')) = (terminal_reason IS NOT NULL)",
            name="ck_flow_instance_terminal_reason",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded','failed','cancelled') OR wait_reason IS NOT NULL "
            "OR status = 'pending'",
            name="ck_flow_instance_wait_reason",
        ),
    )
    op.create_index(
        "ix_flow_instances_run_status",
        "director_business_flow_instances",
        ["project_id", "supervisor_run_id", "status"],
    )
    op.create_index(
        "ix_flow_instances_active",
        "director_business_flow_instances",
        ["updated_at", "id"],
        postgresql_where=sa.text("status NOT IN ('succeeded','failed','cancelled')"),
    )

    op.create_table(
        "director_business_flow_steps",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.Column("supervisor_run_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(120), nullable=False),
        sa.Column("scope_type", sa.String(24), nullable=False),
        sa.Column("scope_entity_id", sa.UUID(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("input_refs", postgresql.JSONB(), nullable=False),
        sa.Column("completion_spec", postgresql.JSONB(), nullable=False),
        sa.Column("dependencies", postgresql.JSONB(), nullable=False),
        sa.Column("result_refs", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("wait_reason", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("instance_id", "step_key", name="uq_flow_step_instance_key"),
        sa.UniqueConstraint(
            "id", "instance_id", "supervisor_run_id", "plan_id", "plan_revision",
            "project_id", "scope_type", "scope_entity_id",
            name="uq_flow_step_attempt_identity",
        ),
        sa.ForeignKeyConstraint(
            ["instance_id", "supervisor_run_id", "plan_id", "plan_revision", "project_id"],
            [
                "director_business_flow_instances.id",
                "director_business_flow_instances.supervisor_run_id",
                "director_business_flow_instances.plan_id",
                "director_business_flow_instances.plan_revision",
                "director_business_flow_instances.project_id",
            ],
            ondelete="NO ACTION", name="fk_flow_step_instance",
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint("revision > 0", name="ck_flow_step_revision"),
        sa.CheckConstraint(_in("status", STEP_STATUSES), name="ck_flow_step_status"),
        sa.CheckConstraint("scope_type IN ('project','scene','shot')", name="ck_flow_step_scope"),
    )
    op.create_index(
        "ix_flow_steps_instance_status",
        "director_business_flow_steps",
        ["instance_id", "status", "step_key"],
    )

    op.create_table(
        "director_business_flow_step_attempts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.Column("supervisor_run_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(24), nullable=False),
        sa.Column("scope_entity_id", sa.UUID(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("control_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("payload_hash", sa.CHAR(64), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("action_kind", sa.String(32), nullable=False),
        sa.Column("action_key", sa.String(120), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("authorization_ref", sa.UUID(), nullable=True),
        sa.Column("node_run_id", sa.UUID(), nullable=True),
        sa.Column("receipt_ref", postgresql.JSONB(), nullable=True),
        sa.Column("result_refs", postgresql.JSONB(), nullable=False),
        sa.Column(
            "unresolved_external", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("step_id", "attempt_no", name="uq_flow_attempt_step_no"),
        sa.UniqueConstraint("project_id", "command_key", name="uq_flow_attempt_command"),
        sa.UniqueConstraint(
            "id", "supervisor_run_id", "plan_revision", "project_id",
            "scope_type", "scope_entity_id",
            name="uq_flow_attempt_turn_identity",
        ),
        sa.ForeignKeyConstraint(
            [
                "step_id", "instance_id", "supervisor_run_id", "plan_id", "plan_revision",
                "project_id", "scope_type", "scope_entity_id",
            ],
            [
                "director_business_flow_steps.id",
                "director_business_flow_steps.instance_id",
                "director_business_flow_steps.supervisor_run_id",
                "director_business_flow_steps.plan_id",
                "director_business_flow_steps.plan_revision",
                "director_business_flow_steps.project_id",
                "director_business_flow_steps.scope_type",
                "director_business_flow_steps.scope_entity_id",
            ],
            ondelete="NO ACTION", name="fk_flow_attempt_step",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["node_run_id", "project_id"], ["node_runs.id", "node_runs.project_id"],
            ondelete="NO ACTION", name="fk_flow_attempt_node_run",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["authorization_ref", "project_id"],
            ["production_command_authorizations.id", "production_command_authorizations.project_id"],
            ondelete="NO ACTION", name="fk_flow_attempt_authorization",
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint("revision > 0", name="ck_flow_attempt_revision"),
        sa.CheckConstraint("attempt_no > 0", name="ck_flow_attempt_no"),
        sa.CheckConstraint("control_epoch >= 0", name="ck_flow_attempt_epoch"),
        sa.CheckConstraint(_in("status", ATTEMPT_STATUSES), name="ck_flow_attempt_status"),
        sa.CheckConstraint(_in("action_kind", ACTION_KINDS), name="ck_flow_attempt_action_kind"),
        sa.CheckConstraint("scope_type IN ('project','scene','shot')", name="ck_flow_attempt_scope"),
        sa.CheckConstraint(
            "status <> 'unknown_submission' OR unresolved_external",
            name="ck_flow_attempt_unknown_unresolved",
        ),
        sa.CheckConstraint(
            "action_kind <> 'production' OR status <> 'succeeded' OR node_run_id IS NOT NULL",
            name="ck_flow_attempt_production_receipt",
        ),
    )
    op.create_index(
        "ix_flow_attempts_project_status",
        "director_business_flow_step_attempts",
        ["project_id", "status", "updated_at", "id"],
    )
    op.create_index(
        "uq_flow_attempt_active_step",
        "director_business_flow_step_attempts",
        ["step_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending','running','waiting_user','waiting_execution',"
            "'unknown_submission') OR unresolved_external"
        ),
    )

    op.add_column(
        "director_turns", sa.Column("business_flow_step_attempt_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_director_turn_flow_attempt",
        "director_turns",
        "director_business_flow_step_attempts",
        ["business_flow_step_attempt_id", "master_run_id", "plan_revision", "project_id",
         "scope_type", "scope_entity_id"],
        ["id", "supervisor_run_id", "plan_revision", "project_id", "scope_type", "scope_entity_id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_check_constraint(
        "ck_director_turn_flow_attempt_scope",
        "director_turns",
        "business_flow_step_attempt_id IS NULL OR "
        "(master_run_id IS NOT NULL AND plan_revision IS NOT NULL)",
    )

    for table in (
        "director_business_flow_instances",
        "director_business_flow_steps",
        "director_business_flow_step_attempts",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
            "USING (project_id = app.current_project_id()) "
            "WITH CHECK (project_id = app.current_project_id())"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO dramaforge_app")
        op.execute(f"REVOKE DELETE, TRUNCATE ON {table} FROM dramaforge_app")


def downgrade() -> None:
    # Flow history is evidence, not disposable state: refuse a silent drop.
    present = op.get_bind().execute(
        sa.text("SELECT count(*) FROM director_business_flow_instances")
    ).scalar_one()
    if present:
        raise RuntimeError("BUSINESS_FLOWS_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE")
    op.drop_constraint(
        "ck_director_turn_flow_attempt_scope", "director_turns", type_="check"
    )
    op.drop_constraint(
        "fk_director_turn_flow_attempt", "director_turns", type_="foreignkey"
    )
    op.drop_column("director_turns", "business_flow_step_attempt_id")
    op.drop_table("director_business_flow_step_attempts")
    op.drop_table("director_business_flow_steps")
    op.drop_table("director_business_flow_instances")
    op.drop_constraint(
        "uq_command_auth_scope", "production_command_authorizations", type_="unique"
    )
    op.drop_constraint("uq_node_run_scope", "node_runs", type_="unique")
