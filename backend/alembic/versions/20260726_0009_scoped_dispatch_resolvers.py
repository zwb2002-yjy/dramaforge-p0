"""Add ownership resolvers for scheduled outbox dispatch.

Revision ID: 20260726_0009
Revises: 20260724_0008
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260726_0009"
down_revision: Union[str, None] = "20260724_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_roles WHERE rolname = 'dramaforge_worker_resolver'
          ) THEN
            CREATE ROLE dramaforge_worker_resolver NOLOGIN NOINHERIT BYPASSRLS;
          END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.queued_node_run_contexts(
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
        """
        CREATE OR REPLACE FUNCTION app.pending_outbox_event_contexts(
          p_limit integer,
          p_project_id uuid DEFAULT NULL
        )
        RETURNS TABLE(
          outbox_event_id uuid,
          owner_user_id uuid,
          workspace_id uuid,
          project_id uuid
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT oe.event_id, w.owner_user_id, w.id, p.id
          FROM outbox_events oe
          LEFT JOIN projects p ON p.id = oe.project_id
          LEFT JOIN workspaces w ON w.id = p.workspace_id
          WHERE (
            (oe.status = 'pending' AND oe.next_attempt_at <= now())
            OR (oe.status = 'leased' AND oe.leased_until < now())
          )
            AND (p_project_id IS NULL OR oe.project_id = p_project_id)
          ORDER BY oe.created_at, oe.event_id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION app.queued_node_run_contexts(integer, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute("DROP FUNCTION IF EXISTS app.queued_node_run_contexts(integer)")
    op.execute(
        "ALTER FUNCTION app.pending_outbox_event_contexts(integer, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.queued_node_run_contexts(integer, uuid) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.pending_outbox_event_contexts(integer, uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.queued_node_run_contexts(integer, uuid) "
        "TO dramaforge, dramaforge_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pending_outbox_event_contexts(integer, uuid) "
        "TO dramaforge, dramaforge_app"
    )
    op.execute(
        "GRANT SELECT ON outbox_events, projects, workspaces "
        "TO dramaforge_worker_resolver"
    )
    op.execute("DROP POLICY IF EXISTS outbox_events_project_scope ON outbox_events")
    op.execute(
        """
        CREATE POLICY outbox_events_project_scope ON outbox_events
        FOR ALL
        USING (
          project_id IS NULL
          OR project_id = app.current_project_id()
        )
        WITH CHECK (
          project_id IS NULL
          OR project_id = app.current_project_id()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.pending_outbox_event_contexts(integer, uuid)")
