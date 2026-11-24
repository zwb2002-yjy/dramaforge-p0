"""Persist short Provider poll due time on the original NodeRun."""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0092"
down_revision = "20261028_0091"
branch_labels = None
depends_on = None


def _queued_contexts(*, scheduled: bool) -> None:
    eligibility = "nr.status = 'queued'"
    if scheduled:
        eligibility = """(nr.status = 'queued' OR
            (nr.status = 'cancel_requested' AND nr.started_at IS NULL))
            AND (nr.next_attempt_at IS NULL OR nr.next_attempt_at <= now())"""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION app.queued_node_run_contexts(
            p_limit integer, p_project_id uuid DEFAULT NULL, p_source_commit text DEFAULT NULL
        )
        RETURNS TABLE(node_run_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
            SELECT nr.id, w.owner_user_id, w.id, p.id
            FROM public.node_runs nr
            JOIN public.projects p ON p.id = nr.project_id
            JOIN public.workspaces w ON w.id = p.workspace_id
            WHERE {eligibility}
              AND (p_project_id IS NULL OR nr.project_id = p_project_id)
              AND (p_source_commit IS NULL OR nr.input_snapshot ->> 'source_commit' = p_source_commit)
            ORDER BY nr.created_at, nr.id LIMIT GREATEST(p_limit, 0)
        $$
    """)


def upgrade() -> None:
    op.add_column(
        "node_runs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    if op.get_bind().dialect.name == "postgresql":
        _queued_contexts(scheduled=True)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _queued_contexts(scheduled=False)
    op.drop_column("node_runs", "next_attempt_at")
