"""Add least-privilege Artifact ownership lookup for workspace-level probes.

Revision ID: 20260813_0024
Revises: 20260813_0023
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_0024"
down_revision: str | None = "20260813_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.artifact_context(p_artifact_id uuid)
        RETURNS TABLE (
          owner_user_id uuid,
          workspace_id uuid,
          project_id uuid
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
          SELECT w.owner_user_id, w.id, p.id
          FROM public.artifacts AS a
          JOIN public.projects AS p ON p.id = a.project_id
          JOIN public.workspaces AS w ON w.id = p.workspace_id
          WHERE a.id = p_artifact_id
          LIMIT 1
        $function$
        """
    )
    op.execute(
        "ALTER FUNCTION app.artifact_context(uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute("REVOKE ALL ON FUNCTION app.artifact_context(uuid) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.artifact_context(uuid) "
        "TO dramaforge, dramaforge_app"
    )
    op.execute(
        "GRANT SELECT ON artifacts, projects, workspaces "
        "TO dramaforge_worker_resolver"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.artifact_context(uuid)")
