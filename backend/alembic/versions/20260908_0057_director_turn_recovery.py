"""Expose narrowly scoped recoverable Director turns to the default Worker.

Revision ID: 20260908_0057
Revises: 20260907_0056
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0057"
down_revision: str | None = "20260907_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON director_turns TO dramaforge_worker_resolver")
    op.execute(
        """
        CREATE FUNCTION app.recoverable_director_turn_contexts(
          p_limit integer,
          p_stale_before timestamptz
        )
        RETURNS TABLE(turn_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT dt.id, w.owner_user_id, w.id, p.id
          FROM director_turns dt
          JOIN projects p ON p.id = dt.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE dt.status IN ('queued', 'thinking', 'awaiting_user', 'awaiting_execution')
            AND (
              (dt.deadline IS NOT NULL AND dt.deadline <= now())
              OR (
                dt.status = 'thinking'
                AND dt.transport_status = 'submission_started'
                AND dt.updated_at < p_stale_before
              )
            )
          ORDER BY dt.updated_at, dt.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION app.recoverable_director_turn_contexts(integer, timestamptz) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.recoverable_director_turn_contexts(integer, timestamptz) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.recoverable_director_turn_contexts(integer, timestamptz) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS app.recoverable_director_turn_contexts(integer, timestamptz)"
    )
    op.execute("REVOKE SELECT ON director_turns FROM dramaforge_worker_resolver")
