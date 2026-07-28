"""Require an explicit workspace RLS context for projects.

Revision ID: 20260726_0010
Revises: 20260726_0009
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260726_0010"
down_revision: Union[str, None] = "20260726_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS projects_workspace_scope ON projects")
    op.execute(
        """
        CREATE POLICY projects_workspace_scope ON projects
        FOR ALL
        USING (
          projects.workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = projects.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
          AND (
            app.current_project_id() IS NULL
            OR projects.id = app.current_project_id()
          )
        )
        WITH CHECK (
          projects.workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = projects.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
          AND (
            app.current_project_id() IS NULL
            OR projects.id = app.current_project_id()
          )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS projects_workspace_scope ON projects")
    op.execute(
        """
        CREATE POLICY projects_workspace_scope ON projects
        FOR ALL
        USING (
          EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = projects.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
          AND (
            app.current_workspace_id() IS NULL
            OR projects.workspace_id = app.current_workspace_id()
          )
          AND (
            app.current_project_id() IS NULL
            OR projects.id = app.current_project_id()
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = projects.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
          AND (
            app.current_workspace_id() IS NULL
            OR projects.workspace_id = app.current_workspace_id()
          )
          AND (
            app.current_project_id() IS NULL
            OR projects.id = app.current_project_id()
          )
        )
        """
    )
