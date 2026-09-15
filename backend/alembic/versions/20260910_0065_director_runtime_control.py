"""Bind new Director turns to one engine execution and fence resume work."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260910_0065"
down_revision = "20260910_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("director_turns", sa.Column("engine_version", sa.String(120)))
    op.add_column("director_turns", sa.Column("state_schema_version", sa.String(120)))
    op.add_column("director_turns", sa.Column("runtime_execution_id", sa.UUID()))
    op.add_column("director_turns", sa.Column("runtime_revision", sa.Integer()))
    op.create_unique_constraint(
        "uq_director_turn_runtime_execution", "director_turns", ["runtime_execution_id"],
    )
    op.create_check_constraint(
        "ck_director_turn_engine_binding",
        "director_turns",
        "(engine_version IS NULL AND state_schema_version IS NULL AND "
        "runtime_execution_id IS NULL) OR (engine_version IS NOT NULL AND "
        "state_schema_version IS NOT NULL AND runtime_execution_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_director_turn_runtime_revision",
        "director_turns",
        "runtime_revision IS NULL OR runtime_revision > 0",
    )
    op.create_table(
        "director_runtime_controls",
        sa.Column("runtime_execution_id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("engine_version", sa.String(120), nullable=False),
        sa.Column("state_schema_version", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("stop_requested_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["turn_id", "project_id"],
            ["director_turns.id", "director_turns.project_id"],
            ondelete="CASCADE",
            name="fk_director_runtime_control_turn_scope",
        ),
        sa.UniqueConstraint("turn_id", name="uq_director_runtime_control_turn"),
        sa.UniqueConstraint(
            "runtime_execution_id", "project_id",
            name="uq_director_runtime_control_execution_scope",
        ),
        sa.CheckConstraint("revision > 0", name="ck_director_runtime_control_revision"),
        sa.CheckConstraint("lease_epoch >= 0", name="ck_director_runtime_control_epoch"),
        sa.CheckConstraint(
            "status IN ('active','waiting','stopped','completed','failed','stale')",
            name="ck_director_runtime_control_status",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_director_runtime_control_lease",
        ),
    )
    op.create_table(
        "director_runtime_signal_claims",
        sa.Column("signal_id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("runtime_execution_id", sa.UUID(), primary_key=True),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("reference_id", sa.UUID(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["runtime_execution_id", "project_id"],
            [
                "director_runtime_controls.runtime_execution_id",
                "director_runtime_controls.project_id",
            ],
            ondelete="CASCADE",
            name="fk_director_runtime_signal_execution_scope",
        ),
        sa.CheckConstraint(
            "expected_revision > 0", name="ck_director_runtime_signal_revision",
        ),
        sa.CheckConstraint("lease_epoch > 0", name="ck_director_runtime_signal_epoch"),
    )
    op.create_table(
        "director_runtime_wakeups",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("runtime_execution_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("dead_letter_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["runtime_execution_id", "project_id"],
            [
                "director_runtime_controls.runtime_execution_id",
                "director_runtime_controls.project_id",
            ],
            ondelete="CASCADE",
            name="fk_director_runtime_wakeup_execution_scope",
        ),
        sa.UniqueConstraint(
            "project_id", "dedupe_key", name="uq_director_runtime_wakeup_dedupe",
        ),
        sa.CheckConstraint(
            "kind IN ('start','resume','stop','recovery')",
            name="ck_director_runtime_wakeup_kind",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5",
            name="ck_director_runtime_wakeup_attempts",
        ),
    )
    op.create_index(
        "ix_director_runtime_wakeups_pending",
        "director_runtime_wakeups",
        ["next_attempt_at", "id"],
        postgresql_where=sa.text("completed_at IS NULL AND dead_letter_at IS NULL"),
    )
    for table in (
        "director_runtime_controls",
        "director_runtime_signal_claims",
        "director_runtime_wakeups",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_scope ON {table} FOR ALL "
            "USING (project_id = app.current_project_id()) "
            "WITH CHECK (project_id = app.current_project_id())"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dramaforge_app")
    op.execute("""
        CREATE FUNCTION app.pending_director_runtime_wakeups(p_wakeup_id uuid DEFAULT NULL)
        RETURNS TABLE(
          wakeup_id uuid, turn_id uuid, owner_user_id uuid,
          workspace_id uuid, project_id uuid
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT r.id, c.turn_id, w.owner_user_id, p.workspace_id, p.id
          FROM director_runtime_wakeups r
          JOIN director_runtime_controls c
            ON c.runtime_execution_id = r.runtime_execution_id
           AND c.project_id = r.project_id
          JOIN director_turns t ON t.id = c.turn_id AND t.project_id = c.project_id
          JOIN projects p ON p.id = r.project_id AND p.workspace_id = t.workspace_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE r.completed_at IS NULL AND r.dead_letter_at IS NULL
            AND r.next_attempt_at <= now()
            AND (p_wakeup_id IS NULL OR r.id = p_wakeup_id)
          ORDER BY r.next_attempt_at, r.id LIMIT 50
        $$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION app.pending_director_runtime_wakeups(uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pending_director_runtime_wakeups(uuid) "
        "TO dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION app.pending_director_runtime_wakeups(uuid)")
    op.drop_table("director_runtime_wakeups")
    op.drop_table("director_runtime_signal_claims")
    op.drop_table("director_runtime_controls")
    op.drop_constraint("ck_director_turn_runtime_revision", "director_turns", type_="check")
    op.drop_constraint("ck_director_turn_engine_binding", "director_turns", type_="check")
    op.drop_constraint("uq_director_turn_runtime_execution", "director_turns", type_="unique")
    op.drop_column("director_turns", "runtime_execution_id")
    op.drop_column("director_turns", "runtime_revision")
    op.drop_column("director_turns", "state_schema_version")
    op.drop_column("director_turns", "engine_version")
