"""Expose accepted Agent Turns to the Director worker and recover lost leases.

The HTTP acceptance is already durable in ``director_turns`` / ``director_messages``
/ ``outbox_events``; this migration adds no new table. It adds the two narrowly
scoped SECURITY DEFINER scans the worker needs:

* ``app.pending_agent_director_turns`` lists queued Agent Turns (and resolves one
  Turn's ownership before any project-scoped read);
* ``app.recoverable_director_turn_contexts`` now also reports an Agent Turn whose
  worker lease expired, so a crashed owner becomes terminal instead of hanging.

Revision ID: 20261118_0106
Revises: 20261117_0105
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261118_0106"
down_revision: str | None = "20261117_0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_recovery_scan(*, agent_lease: bool) -> None:
    # CREATE OR REPLACE retains the existing owner and EXECUTE grants.
    # upgrade: the 0097 scan without its Agent exclusion, plus lease expiry.
    # downgrade: restore the 0097 definition exactly.
    kind_filter = "" if agent_lease else "AND dt.turn_kind <> 'agent'"
    lease_clause = (
        """
            OR (
              dt.turn_kind = 'agent'
              AND dt.status = 'thinking'
              AND dt.agent_lease_expires_at IS NOT NULL
              AND dt.agent_lease_expires_at <= now()
            )"""
        if agent_lease
        else ""
    )
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
              ){lease_clause}
            )
          ORDER BY dt.updated_at, dt.id
          LIMIT GREATEST(p_limit, 0)
        $$
    """)


def upgrade() -> None:
    op.execute("GRANT SELECT ON director_turns TO dramaforge_worker_resolver")
    op.execute("""
        CREATE FUNCTION app.pending_agent_director_turns(
          p_limit integer DEFAULT 50,
          p_after_turn_id uuid DEFAULT NULL,
          p_turn_id uuid DEFAULT NULL
        )
        RETURNS TABLE(turn_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT rows.turn_id, rows.owner_user_id, rows.workspace_id, rows.project_id
          FROM (
            SELECT dt.id AS turn_id, w.owner_user_id, w.id AS workspace_id, p.id AS project_id
            FROM director_turns dt
            JOIN projects p ON p.id = dt.project_id
            JOIN workspaces w ON w.id = p.workspace_id
            WHERE p_turn_id IS NOT NULL AND dt.id = p_turn_id
            UNION ALL
            SELECT dt.id AS turn_id, w.owner_user_id, w.id AS workspace_id, p.id AS project_id
            FROM director_turns dt
            JOIN projects p ON p.id = dt.project_id
            JOIN workspaces w ON w.id = p.workspace_id
            WHERE p_turn_id IS NULL
              AND dt.turn_kind = 'agent'
              AND dt.status = 'queued'
              AND (dt.deadline IS NULL OR dt.deadline > now())
              AND (p_after_turn_id IS NULL OR dt.id > p_after_turn_id)
          ) rows
          ORDER BY rows.turn_id
          LIMIT GREATEST(COALESCE(p_limit, 50), 0)
        $$
    """)
    op.execute(
        "ALTER FUNCTION app.pending_agent_director_turns(integer, uuid, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.pending_agent_director_turns(integer, uuid, uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pending_agent_director_turns(integer, uuid, uuid) "
        "TO dramaforge, dramaforge_app"
    )
    _replace_recovery_scan(agent_lease=True)


def downgrade() -> None:
    _replace_recovery_scan(agent_lease=False)
    op.execute("DROP FUNCTION IF EXISTS app.pending_agent_director_turns(integer, uuid, uuid)")
    op.execute("REVOKE SELECT ON director_turns FROM dramaforge_worker_resolver")
