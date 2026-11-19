"""Continuous-goal MasterRun, immutable plans and control receipts (M02).

The Run and Plan tables point at each other, so the pointer FK is created last
with ALTER. Plan/Receipt are append-only: the schema-wide default privileges
grant the runtime role every verb on new tables, so UPDATE/DELETE are revoked
explicitly instead of merely not granted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20261117_0102"
down_revision = "20261117_0101"
branch_labels = None
depends_on = None

TERMINAL = "('succeeded','failed','cancelled')"


def _immutable(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT ON {table} TO dramaforge_app")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM dramaforge_app")


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
        "USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )


def upgrade() -> None:
    # Candidate keys the new composite foreign keys resolve against.
    op.create_unique_constraint(
        "uq_director_proposal_item_scope", "director_proposal_items", ["id", "project_id"],
    )
    op.create_unique_constraint(
        "uq_director_turn_origin_identity", "director_turns",
        ["id", "project_id", "workspace_id", "actor_id", "thread_id", "turn_kind"],
    )
    op.add_column("director_turns", sa.Column("master_run_id", sa.UUID(), nullable=True))
    op.add_column("director_turns", sa.Column("plan_revision", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_director_turn_run_scope", "director_turns", ["id", "master_run_id", "project_id"],
    )
    op.create_unique_constraint(
        "uq_director_turn_plan_scope", "director_turns",
        ["id", "master_run_id", "plan_revision", "project_id"],
    )
    op.create_check_constraint(
        "ck_director_turn_master_plan", "director_turns",
        "(plan_revision IS NULL OR plan_revision > 0) AND "
        "(plan_revision IS NULL OR master_run_id IS NOT NULL)",
    )

    op.create_table(
        "director_master_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("source_thread_id", sa.UUID(), nullable=False),
        sa.Column("origin_turn_id", sa.UUID(), nullable=False),
        sa.Column("origin_turn_kind", sa.String(16), nullable=False, server_default="agent"),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("current_plan_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="planning"),
        sa.Column("desired_state", sa.String(16), nullable=False, server_default="run"),
        sa.Column("wait_reason", sa.String(80), nullable=True),
        sa.Column("control_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"], ["projects.id", "projects.workspace_id"],
            name="fk_master_run_project_scope", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_thread_id", "project_id"],
            ["director_threads.id", "director_threads.project_id"],
            name="fk_master_run_thread_scope", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["origin_turn_id", "project_id", "workspace_id", "actor_id",
             "source_thread_id", "origin_turn_kind"],
            ["director_turns.id", "director_turns.project_id", "director_turns.workspace_id",
             "director_turns.actor_id", "director_turns.thread_id", "director_turns.turn_kind"],
            name="fk_master_run_origin_turn", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_master_run_scope"),
        sa.UniqueConstraint(
            "id", "project_id", "workspace_id", "actor_id", name="uq_master_run_owner",
        ),
        sa.UniqueConstraint("project_id", "origin_turn_id", name="uq_master_run_origin"),
        sa.CheckConstraint("origin_turn_kind = 'agent'", name="ck_master_run_origin_kind"),
        sa.CheckConstraint(
            "length(trim(goal)) >= 1 AND length(goal) <= 16000", name="ck_master_run_goal",
        ),
        sa.CheckConstraint("control_epoch >= 0", name="ck_master_run_control_epoch"),
        sa.CheckConstraint("revision > 0", name="ck_master_run_revision"),
        sa.CheckConstraint(
            "status IN ('planning','running','waiting','paused','stopping',"
            "'succeeded','failed','cancelled')",
            name="ck_master_run_status",
        ),
        sa.CheckConstraint(
            "desired_state IN ('run','pause','cancel')", name="ck_master_run_desired_state",
        ),
        sa.CheckConstraint(
            f"(status IN {TERMINAL}) = (finished_at IS NOT NULL)", name="ck_master_run_finished",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="ck_master_run_finished_after_create",
        ),
        sa.CheckConstraint(
            "deadline_at IS NULL OR deadline_at >= created_at",
            name="ck_master_run_deadline_after_create",
        ),
        sa.CheckConstraint(
            f"archived_at IS NULL OR (status IN {TERMINAL} AND finished_at IS NOT NULL "
            "AND archived_at >= finished_at)",
            name="ck_master_run_archive_terminal",
        ),
    )
    op.create_index(
        "ix_master_run_status", "director_master_runs",
        ["project_id", "status", "updated_at", "id"],
    )
    op.create_index(
        "ix_master_run_thread", "director_master_runs", ["source_thread_id", "created_at", "id"],
    )

    op.create_table(
        "director_master_run_plans",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("master_run_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column("plan_hash", sa.CHAR(64), nullable=False),
        sa.Column("plan_data", postgresql.JSONB(), nullable=False),
        sa.Column("decision_ref", sa.UUID(), nullable=False),
        sa.Column("created_by_turn_id", sa.UUID(), nullable=True),
        sa.Column("created_by_actor_id", sa.UUID(),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["master_run_id", "project_id"],
            ["director_master_runs.id", "director_master_runs.project_id"],
            name="fk_master_run_plan_run", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["decision_ref", "project_id"],
            ["director_proposal_items.id", "director_proposal_items.project_id"],
            name="fk_master_run_plan_decision", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_turn_id", "master_run_id", "project_id"],
            ["director_turns.id", "director_turns.master_run_id", "director_turns.project_id"],
            name="fk_master_run_plan_turn", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint("master_run_id", "revision", name="uq_master_run_plan_revision"),
        sa.UniqueConstraint("master_run_id", "plan_hash", name="uq_master_run_plan_hash"),
        sa.UniqueConstraint("id", "master_run_id", "project_id", name="uq_master_run_plan_scope"),
        sa.UniqueConstraint(
            "master_run_id", "revision", "project_id", name="uq_master_run_plan_revision_scope",
        ),
        sa.UniqueConstraint(
            "id", "revision", "master_run_id", "project_id",
            name="uq_master_run_plan_revision_identity",
        ),
        sa.UniqueConstraint("project_id", "decision_ref", name="uq_master_run_plan_decision"),
        sa.CheckConstraint("revision > 0", name="ck_master_run_plan_revision"),
    )
    op.create_index(
        "ix_master_run_plan_run", "director_master_run_plans",
        ["project_id", "master_run_id", "created_at", "id"],
    )

    op.create_table(
        "director_master_run_control_receipts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("master_run_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("result_revision", sa.Integer(), nullable=False),
        sa.Column("result_data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["master_run_id", "project_id"],
            ["director_master_runs.id", "director_master_runs.project_id"],
            name="fk_master_run_receipt_run", ondelete="NO ACTION",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "master_run_id", "expected_revision", "operation", name="uq_master_run_receipt_key",
        ),
        sa.CheckConstraint(
            "operation IN ('pause','resume','cancel','verify')",
            name="ck_master_run_receipt_operation",
        ),
        sa.CheckConstraint("expected_revision > 0", name="ck_master_run_receipt_expected"),
        sa.CheckConstraint(
            "result_revision = expected_revision + 1", name="ck_master_run_receipt_result",
        ),
    )
    op.create_index(
        "ix_master_run_receipt_run", "director_master_run_control_receipts",
        ["project_id", "master_run_id", "created_at", "id"],
    )

    # Deferred cross-table pointers and the Run -> Turn binding, added last.
    op.create_foreign_key(
        "fk_master_run_current_plan",
        "director_master_runs", "director_master_run_plans",
        ["current_plan_id", "id", "project_id"],
        ["id", "master_run_id", "project_id"],
        ondelete="NO ACTION", deferrable=True, initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_director_turn_master_run",
        "director_turns", "director_master_runs",
        ["master_run_id", "project_id"],
        ["id", "project_id"],
        ondelete="NO ACTION", deferrable=True, initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_director_turn_master_plan",
        "director_turns", "director_master_run_plans",
        ["master_run_id", "plan_revision", "project_id"],
        ["master_run_id", "revision", "project_id"],
        ondelete="NO ACTION", deferrable=True, initially="DEFERRED",
    )

    for table in (
        "director_master_runs",
        "director_master_run_plans",
        "director_master_run_control_receipts",
    ):
        _rls(table)
    # The Run row is the only mutable record (status/desired_state/revision/...).
    op.execute("GRANT SELECT, INSERT, UPDATE ON director_master_runs TO dramaforge_app")
    op.execute(
        "REVOKE DELETE, TRUNCATE ON director_master_runs FROM dramaforge_app"
    )
    _immutable("director_master_run_plans")
    _immutable("director_master_run_control_receipts")


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("MASTER_RUN_DOWNGRADE_REQUIRES_ONLINE_PREFLIGHT")
    connection = op.get_bind()
    populated = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM director_master_runs) "
            "OR EXISTS(SELECT 1 FROM director_master_run_plans) "
            "OR EXISTS(SELECT 1 FROM director_master_run_control_receipts)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("MASTER_RUNS_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE")
    for table in (
        "director_master_run_control_receipts",
        "director_master_run_plans",
        "director_master_runs",
    ):
        op.execute(f"DROP POLICY {table}_project_scope ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_constraint("fk_director_turn_master_plan", "director_turns", type_="foreignkey")
    op.drop_constraint("fk_director_turn_master_run", "director_turns", type_="foreignkey")
    op.drop_constraint("fk_master_run_current_plan", "director_master_runs", type_="foreignkey")
    op.drop_index("ix_master_run_receipt_run", table_name="director_master_run_control_receipts")
    op.drop_table("director_master_run_control_receipts")
    op.drop_index("ix_master_run_plan_run", table_name="director_master_run_plans")
    op.drop_table("director_master_run_plans")
    op.drop_index("ix_master_run_thread", table_name="director_master_runs")
    op.drop_index("ix_master_run_status", table_name="director_master_runs")
    op.drop_table("director_master_runs")
    op.drop_constraint("ck_director_turn_master_plan", "director_turns", type_="check")
    op.drop_constraint("uq_director_turn_plan_scope", "director_turns", type_="unique")
    op.drop_constraint("uq_director_turn_run_scope", "director_turns", type_="unique")
    op.drop_column("director_turns", "plan_revision")
    op.drop_column("director_turns", "master_run_id")
    op.drop_constraint(
        "uq_director_turn_origin_identity", "director_turns", type_="unique",
    )
    op.drop_constraint(
        "uq_director_proposal_item_scope", "director_proposal_items", type_="unique",
    )
