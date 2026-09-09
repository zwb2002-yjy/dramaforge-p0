"""Include persisted Formal checkpoints in the bounded Director recovery scan.

Revision ID: 20260908_0059
Revises: 20260908_0058
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0059"
down_revision: str | None = "20260908_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace(*, include_formal: bool) -> None:
    additional = " OR dt.node_run_ids <> '[]'::jsonb" if include_formal else ""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app.reconcilable_director_turn_contexts(
            p_limit integer, p_after_turn_id uuid DEFAULT NULL
        )
        RETURNS TABLE(turn_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
          SELECT dt.id, w.owner_user_id, w.id, p.id
          FROM director_turns dt
          JOIN projects p ON p.id = dt.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE (dt.status = 'awaiting_execution'
            OR (dt.status = 'awaiting_user' AND (dt.proposal_id IS NOT NULL{additional})))
            AND (p_after_turn_id IS NULL OR dt.id > p_after_turn_id)
          ORDER BY dt.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )


def upgrade() -> None:
    _replace(include_formal=True)


def downgrade() -> None:
    _replace(include_formal=False)
