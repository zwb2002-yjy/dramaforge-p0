"""Bounded keyset discovery for periodic persisted Provider recovery.

The original two-argument resolver remains available for rolling deployments.
Only ownership identifiers are exposed; all writes still use project RLS.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0073"
down_revision: str | None = "20260917_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIGNATURE = "app.resumable_provider_node_run_contexts(integer,text,uuid,timestamptz)"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.resumable_provider_node_run_contexts(
          p_limit integer,
          p_source_commit text,
          p_after_node_run_id uuid,
          p_stale_before timestamptz
        )
        RETURNS TABLE(node_run_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT nr.id, w.owner_user_id, w.id, p.id
          FROM node_runs nr
          JOIN LATERAL (
            SELECT po.* FROM provider_operations po
            WHERE po.node_run_id = nr.id AND po.execution_path_version = 'unified-v1'
            ORDER BY po.attempt_no DESC, po.created_at DESC
            LIMIT 1
          ) po ON true
          JOIN projects p ON p.id = nr.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE nr.status IN ('running', 'cancel_requested')
            AND (p_after_node_run_id IS NULL OR nr.id > p_after_node_run_id)
            AND coalesce(nr.started_at, nr.created_at)
                < LEAST(p_stale_before, now() - interval '31 minutes')
            AND coalesce(po.last_polled_at, po.submitted_at, po.created_at)
                < LEAST(p_stale_before, now() - interval '31 minutes')
            AND ((po.provider_operation_id IS NOT NULL
                  AND po.status IN ('submitted', 'running', 'timed_out', 'cancel_requested'))
                 OR (po.provider_operation_id IS NULL AND po.status = 'submission_started'
                     AND po.created_at < LEAST(p_stale_before, now() - interval '31 minutes')))
            AND (p_source_commit IS NULL
                 OR nr.input_snapshot ->> 'source_commit' = p_source_commit)
          ORDER BY nr.id
          LIMIT LEAST(GREATEST(p_limit, 0), 50)
        $$
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO dramaforge_worker_resolver")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO dramaforge, dramaforge_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {_SIGNATURE}")
