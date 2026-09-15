"""Atomically retain director receipts and wakeup intent across process loss."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0062"
down_revision = "20260909_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "director_inbox",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consumer_id", sa.String(100), nullable=False),
        sa.Column("event_id", sa.UUID(), sa.ForeignKey("event_log.event_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("consumer_id", "event_id", name="uq_director_inbox_event"),
    )
    op.create_table(
        "director_wakeups",
        sa.Column("inbox_id", sa.UUID(), sa.ForeignKey("director_inbox.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("dead_letter_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(120)),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 5", name="ck_director_wakeup_attempts"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for table in ("director_inbox", "director_wakeups"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} FOR ALL "
                   "USING (project_id = app.current_project_id()) "
                   "WITH CHECK (project_id = app.current_project_id())")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dramaforge_app")
    op.execute("""
        CREATE FUNCTION app.director_production_event_context(p_event_id uuid)
        RETURNS TABLE(owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT w.owner_user_id, p.workspace_id, p.id
          FROM event_log e
          JOIN outbox_events o ON o.event_id = e.event_id
          JOIN projects p ON p.id = e.project_id AND p.id = o.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE e.event_id = p_event_id AND o.topic = 'production.facts.v1'
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.director_production_event_context(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.director_production_event_context(uuid) TO dramaforge_app")
    op.execute("""
        CREATE FUNCTION app.pending_director_wakeups(p_inbox_id uuid DEFAULT NULL)
        RETURNS TABLE(inbox_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT d.inbox_id, w.owner_user_id, p.workspace_id, p.id
          FROM director_wakeups d
          JOIN projects p ON p.id = d.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE d.completed_at IS NULL AND d.dead_letter_at IS NULL
            AND d.next_attempt_at <= now()
            AND (p_inbox_id IS NULL OR d.inbox_id = p_inbox_id)
          ORDER BY d.created_at, d.inbox_id LIMIT 50
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.pending_director_wakeups(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.pending_director_wakeups(uuid) TO dramaforge_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.pending_director_wakeups(uuid)")
    op.execute("DROP FUNCTION app.director_production_event_context(uuid)")
    op.drop_table("director_wakeups")
    op.drop_table("director_inbox")
