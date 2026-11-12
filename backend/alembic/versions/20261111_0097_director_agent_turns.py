"""Link Agent conversations, fence controls, and persist scoped tool-call evidence.

Historical Turns retain their workflow kind and no invented thread or engine
identity. Existing messages remain unlinked unless created by the Agent path.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261111_0097"
down_revision = "20261103_0096"
branch_labels = None
depends_on = None


def _replace_worker_scans(*, exclude_agent: bool) -> None:
    # CREATE OR REPLACE retains the existing function owner and EXECUTE grants.
    # These are the 0057/0059 scans, with only the new turn-kind filter added.
    kind_filter = "AND dt.turn_kind <> 'agent'" if exclude_agent else ""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION app.recoverable_director_turn_contexts(
          p_limit integer, p_stale_before timestamptz
        )
        RETURNS TABLE(turn_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT dt.id, w.owner_user_id, w.id, p.id
          FROM director_turns dt
          JOIN projects p ON p.id = dt.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE dt.status IN ('queued', 'thinking', 'awaiting_user', 'awaiting_execution')
            {kind_filter}
            AND (
              (dt.deadline IS NOT NULL AND dt.deadline <= now())
              OR (
                dt.status = 'thinking'
                AND dt.transport_status = 'submission_started'
                AND dt.updated_at < p_stale_before
              )
            )
          ORDER BY dt.updated_at, dt.id
          LIMIT GREATEST(p_limit, 0)
        $$
    """)
    op.execute(f"""
        CREATE OR REPLACE FUNCTION app.reconcilable_director_turn_contexts(
          p_limit integer, p_after_turn_id uuid DEFAULT NULL
        )
        RETURNS TABLE(turn_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT dt.id, w.owner_user_id, w.id, p.id
          FROM director_turns dt
          JOIN projects p ON p.id = dt.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE (dt.status = 'awaiting_execution'
            OR (dt.status = 'awaiting_user'
                AND (dt.proposal_id IS NOT NULL OR dt.node_run_ids <> '[]'::jsonb)))
            {kind_filter}
            AND (p_after_turn_id IS NULL OR dt.id > p_after_turn_id)
          ORDER BY dt.id
          LIMIT GREATEST(p_limit, 0)
        $$
    """)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_director_thread_project", "director_threads", ["id", "project_id"]
    )
    op.add_column("director_turns", sa.Column("thread_id", sa.UUID(), nullable=True))
    op.add_column(
        "director_turns",
        sa.Column("turn_kind", sa.String(16), nullable=False, server_default="workflow"),
    )
    op.add_column("director_turns", sa.Column("origin_agent_turn_id", sa.UUID(), nullable=True))
    op.add_column(
        "director_turns",
        sa.Column("agent_control_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("director_turns", sa.Column("agent_lease_token", sa.UUID(), nullable=True))
    op.add_column(
        "director_turns",
        sa.Column("agent_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "director_turns", sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_director_turn_thread_scope",
        "director_turns",
        "director_threads",
        ["thread_id", "project_id"],
        ["id", "project_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_director_turn_origin_scope",
        "director_turns",
        "director_turns",
        ["origin_agent_turn_id", "project_id"],
        ["id", "project_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_director_turn_kind", "director_turns", "turn_kind IN ('agent','workflow')"
    )
    op.create_check_constraint(
        "ck_director_turn_control_epoch", "director_turns", "agent_control_epoch >= 0"
    )
    op.create_index("ix_director_turns_thread", "director_turns", ["thread_id", "created_at"])
    op.create_index("ix_director_turns_origin", "director_turns", ["origin_agent_turn_id"])

    op.add_column("director_messages", sa.Column("turn_id", sa.UUID(), nullable=True))
    op.add_column("director_messages", sa.Column("ordinal", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_director_message_turn_scope",
        "director_messages",
        "director_turns",
        ["turn_id", "project_id"],
        ["id", "project_id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_director_message_turn_ordinal", "director_messages", ["turn_id", "ordinal"]
    )
    op.create_check_constraint(
        "ck_director_message_ordinal", "director_messages", "ordinal IS NULL OR ordinal >= 0"
    )
    op.create_table(
        "director_tool_calls",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(200), nullable=False),
        sa.Column("tool_name", sa.String(160), nullable=False),
        sa.Column("tool_version", sa.String(80), nullable=False),
        sa.Column("schema_hash", sa.CHAR(64), nullable=False),
        sa.Column("args_hash", sa.CHAR(64), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "project_id"],
            ["director_turns.id", "director_turns.project_id"],
            ondelete="CASCADE",
            name="fk_director_tool_call_turn_scope",
        ),
        sa.UniqueConstraint("turn_id", "call_id", name="uq_director_tool_call_id"),
        sa.CheckConstraint("step >= 0", name="ck_director_tool_call_step"),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled','unknown_submission')",
            name="ck_director_tool_call_status",
        ),
    )
    op.create_index("ix_director_tool_calls_turn_step", "director_tool_calls", ["turn_id", "step"])
    op.execute("ALTER TABLE director_tool_calls ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE director_tool_calls FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY director_tool_calls_project_scope ON director_tool_calls FOR ALL
        USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON director_tool_calls TO dramaforge_app")
    _replace_worker_scans(exclude_agent=True)


def downgrade() -> None:
    _replace_worker_scans(exclude_agent=False)
    op.drop_index("ix_director_tool_calls_turn_step", table_name="director_tool_calls")
    op.drop_table("director_tool_calls")
    op.drop_constraint("ck_director_message_ordinal", "director_messages", type_="check")
    op.drop_constraint("uq_director_message_turn_ordinal", "director_messages", type_="unique")
    op.drop_constraint("fk_director_message_turn_scope", "director_messages", type_="foreignkey")
    op.drop_column("director_messages", "ordinal")
    op.drop_column("director_messages", "turn_id")
    op.drop_index("ix_director_turns_origin", table_name="director_turns")
    op.drop_index("ix_director_turns_thread", table_name="director_turns")
    op.drop_constraint("ck_director_turn_control_epoch", "director_turns", type_="check")
    op.drop_constraint("ck_director_turn_kind", "director_turns", type_="check")
    op.drop_constraint("fk_director_turn_origin_scope", "director_turns", type_="foreignkey")
    op.drop_constraint("fk_director_turn_thread_scope", "director_turns", type_="foreignkey")
    for column in (
        "stop_requested_at",
        "agent_lease_expires_at",
        "agent_lease_token",
        "agent_control_epoch",
        "origin_agent_turn_id",
        "turn_kind",
        "thread_id",
    ):
        op.drop_column("director_turns", column)
    op.drop_constraint("uq_director_thread_project", "director_threads", type_="unique")
