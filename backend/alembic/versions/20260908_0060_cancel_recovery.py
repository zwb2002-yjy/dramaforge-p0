"""Recover submitted Provider tasks whose NodeRun was cancellation-requested.

Revision ID: 20260908_0060
Revises: 20260908_0059
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0060"
down_revision: str | None = "20260908_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace(*, include_cancel_requested: bool) -> None:
    statuses = "IN ('running', 'cancel_requested')" if include_cancel_requested else "= 'running'"
    operation_statuses = (
        "('submitted', 'running', 'timed_out', 'cancel_requested')"
        if include_cancel_requested
        else "('submitted', 'running', 'timed_out')"
    )
    unknown = (
        " OR (po.provider_operation_id IS NULL AND po.status = 'submission_started' "
        "AND po.created_at < now() - interval '30 minutes')"
        if include_cancel_requested else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app.resumable_provider_node_run_contexts(
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
          WHERE nr.status {statuses}
            AND po.execution_path_version = 'unified-v1'
            AND ((po.status IN {operation_statuses}
                  AND po.provider_operation_id IS NOT NULL){unknown})
            AND (
              p_source_commit IS NULL
              OR nr.input_snapshot ->> 'source_commit' = p_source_commit
            )
          ORDER BY nr.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )


def upgrade() -> None:
    _replace(include_cancel_requested=True)


def downgrade() -> None:
    _replace(include_cancel_requested=False)
