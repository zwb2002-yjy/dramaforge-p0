"""Discover durable synchronous image receipts on the existing recovery chain."""

from alembic import op

revision = "20261030_0093"
down_revision = "20261028_0092"
branch_labels = None
depends_on = None


def _recovery_function(*, synchronous: bool) -> None:
    identity = "po.provider_operation_id IS NOT NULL"
    if synchronous:
        identity = f"""({identity} OR
            po.response_summary->'synchronous_result'->>'schema_version' = '1')"""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION app.resumable_provider_node_run_contexts(
          p_limit integer, p_source_commit text, p_after_node_run_id uuid,
          p_stale_before timestamptz
        )
        RETURNS TABLE(node_run_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
          SELECT nr.id, w.owner_user_id, w.id, p.id
          FROM public.node_runs nr
          JOIN LATERAL (
            SELECT po.* FROM public.provider_operations po
            WHERE po.node_run_id = nr.id AND po.execution_path_version = 'unified-v1'
            ORDER BY po.attempt_no DESC, po.created_at DESC LIMIT 1
          ) po ON true
          JOIN public.projects p ON p.id = nr.project_id
          JOIN public.workspaces w ON w.id = p.workspace_id
          WHERE nr.status IN ('running', 'cancel_requested')
            AND (p_after_node_run_id IS NULL OR nr.id > p_after_node_run_id)
            AND coalesce(nr.started_at, nr.created_at)
                < LEAST(p_stale_before, now() - interval '31 minutes')
            AND coalesce(po.last_polled_at, po.submitted_at, po.created_at)
                < LEAST(p_stale_before, now() - interval '31 minutes')
            AND (({identity}
                  AND po.status IN ('submitted', 'running', 'timed_out', 'cancel_requested'))
                 OR (po.provider_operation_id IS NULL AND po.status = 'submission_started'
                     AND po.created_at < LEAST(p_stale_before, now() - interval '31 minutes')))
            AND (p_source_commit IS NULL
                 OR nr.input_snapshot ->> 'source_commit' = p_source_commit)
          ORDER BY nr.id LIMIT LEAST(GREATEST(p_limit, 0), 50)
        $$
    """)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _recovery_function(synchronous=True)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _recovery_function(synchronous=False)
