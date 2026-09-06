"""Expose narrowly scoped resumable Unified Provider runs to Workers.

Revision ID: 20260821_0030
Revises: 20260820_0029
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0030"
down_revision: str | None = "20260820_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.resumable_provider_node_run_contexts(
          p_limit integer,
          p_source_commit text DEFAULT NULL
        )
        RETURNS TABLE(node_run_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT DISTINCT nr.id, w.owner_user_id, w.id, p.id
          FROM node_runs nr
          JOIN provider_operations po ON po.node_run_id = nr.id
          JOIN projects p ON p.id = nr.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE nr.status = 'running'
            AND po.execution_path_version = 'unified-v1'
            AND po.status IN ('submitted', 'running', 'timed_out')
            AND po.provider_operation_id IS NOT NULL
            AND (
              p_source_commit IS NULL
              OR nr.input_snapshot ->> 'source_commit' = p_source_commit
            )
          ORDER BY nr.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION app.resumable_provider_node_run_contexts(integer, text) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.resumable_provider_node_run_contexts(integer, text) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.resumable_provider_node_run_contexts(integer, text) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS app.resumable_provider_node_run_contexts(integer, text)"
    )
