"""Expose Director turns waiting for fact reconciliation.

Revision ID: 20260908_0058
Revises: 20260908_0057
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0058"
down_revision: str | None = "20260908_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.reconcilable_director_turn_contexts(p_limit integer, p_after_turn_id uuid DEFAULT NULL)
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
          WHERE (dt.status = 'awaiting_execution'
             OR (dt.status = 'awaiting_user' AND dt.proposal_id IS NOT NULL))
            AND (p_after_turn_id IS NULL OR dt.id > p_after_turn_id)
          ORDER BY dt.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION app.reconcilable_director_turn_contexts(integer,uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.reconcilable_director_turn_contexts(integer,uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.reconcilable_director_turn_contexts(integer,uuid) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.reconcilable_director_turn_contexts(integer,uuid)")
