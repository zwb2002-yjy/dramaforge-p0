"""Narrow scan for queued research-analysis Turns (I4-02).

The Turn row is the durable wakeup for an accepted analysis: a lost Redis job is
rediscovered by this cursor scan. No analysis job table or new runtime is added.

Revision ID: 20261118_0112
Revises: 20261118_0111
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261118_0112"
down_revision: str | None = "20261118_0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.pending_research_analysis_turns(
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
            WHERE p_turn_id IS NOT NULL
              AND dt.id = p_turn_id
              AND dt.scope_type = 'research_analysis'
            UNION ALL
            SELECT dt.id AS turn_id, w.owner_user_id, w.id AS workspace_id, p.id AS project_id
            FROM director_turns dt
            JOIN projects p ON p.id = dt.project_id
            JOIN workspaces w ON w.id = p.workspace_id
            WHERE p_turn_id IS NULL
              AND dt.scope_type = 'research_analysis'
              AND dt.status = 'queued'
              AND (dt.deadline IS NULL OR dt.deadline > now())
              AND (p_after_turn_id IS NULL OR dt.id > p_after_turn_id)
          ) rows
          ORDER BY rows.turn_id
          LIMIT GREATEST(COALESCE(p_limit, 50), 0)
        $$
    """)
    op.execute(
        "ALTER FUNCTION app.pending_research_analysis_turns(integer, uuid, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.pending_research_analysis_turns(integer, uuid, uuid) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pending_research_analysis_turns(integer, uuid, uuid) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS app.pending_research_analysis_turns(integer, uuid, uuid)"
    )
