"""Expose non-terminal BusinessFlow instances to the Director worker (I6a-02).

One narrowly scoped SECURITY DEFINER scan returns the ownership chain for flow
instances that still have actionable steps, or for one named instance before any
project-scoped read. The worker advances them through the existing controlled
tool registry; no new runtime, queue or state machine.

Revision ID: 20261118_0108
Revises: 20261118_0107
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261118_0108"
down_revision: str | None = "20261118_0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON director_business_flow_instances TO dramaforge_worker_resolver")
    op.execute("GRANT SELECT ON director_business_flow_steps TO dramaforge_worker_resolver")
    op.execute("""
        CREATE FUNCTION app.pending_business_flow_contexts(
          p_limit integer DEFAULT 50,
          p_after_instance_id uuid DEFAULT NULL,
          p_instance_id uuid DEFAULT NULL
        )
        RETURNS TABLE(
          instance_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT i.id, w.owner_user_id, p.workspace_id, p.id
          FROM director_business_flow_instances i
          JOIN projects p ON p.id = i.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE (
              (p_instance_id IS NOT NULL AND i.id = p_instance_id)
              OR (
                p_instance_id IS NULL
                AND i.status NOT IN ('succeeded', 'failed', 'cancelled')
                AND EXISTS (
                  SELECT 1 FROM director_business_flow_steps s
                  WHERE s.instance_id = i.id
                    AND s.project_id = i.project_id
                    AND s.status IN ('pending', 'ready', 'running')
                )
                AND (p_after_instance_id IS NULL OR i.id > p_after_instance_id)
              )
            )
          ORDER BY i.id
          LIMIT GREATEST(COALESCE(p_limit, 50), 0)
        $$
    """)
    op.execute(
        "ALTER FUNCTION app.pending_business_flow_contexts(integer, uuid, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.pending_business_flow_contexts(integer, uuid, uuid) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pending_business_flow_contexts(integer, uuid, uuid) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.pending_business_flow_contexts(integer, uuid, uuid)")
    op.execute("REVOKE SELECT ON director_business_flow_steps FROM dramaforge_worker_resolver")
    op.execute(
        "REVOKE SELECT ON director_business_flow_instances FROM dramaforge_worker_resolver"
    )
