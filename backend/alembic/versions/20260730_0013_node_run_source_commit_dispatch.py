"""Scope formal queued NodeRun dispatch to the creating source commit.

Revision ID: 20260730_0013
Revises: 20260726_0012
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0013"
down_revision: str | None = "20260726_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.queued_node_run_contexts(integer, uuid)")
    op.execute(
        """
        CREATE FUNCTION app.queued_node_run_contexts(
          p_limit integer,
          p_project_id uuid DEFAULT NULL,
          p_source_commit text DEFAULT NULL
        )
        RETURNS TABLE(node_run_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT nr.id, w.owner_user_id, w.id, p.id
          FROM node_runs nr
          JOIN projects p ON p.id = nr.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE nr.status = 'queued'
            AND (p_project_id IS NULL OR nr.project_id = p_project_id)
            AND (
              p_source_commit IS NULL
              OR nr.input_snapshot ->> 'source_commit' = p_source_commit
            )
          ORDER BY nr.created_at, nr.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION app.queued_node_run_contexts(integer, uuid, text) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.queued_node_run_contexts(integer, uuid, text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.queued_node_run_contexts(integer, uuid, text) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.queued_node_run_contexts(integer, uuid, text)")
    op.execute(
        """
        CREATE FUNCTION app.queued_node_run_contexts(
          p_limit integer,
          p_project_id uuid DEFAULT NULL
        )
        RETURNS TABLE(node_run_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT nr.id, w.owner_user_id, w.id, p.id
          FROM node_runs nr
          JOIN projects p ON p.id = nr.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE nr.status = 'queued'
            AND (p_project_id IS NULL OR nr.project_id = p_project_id)
          ORDER BY nr.created_at, nr.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION app.queued_node_run_contexts(integer, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.queued_node_run_contexts(integer, uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.queued_node_run_contexts(integer, uuid) "
        "TO dramaforge, dramaforge_app"
    )
