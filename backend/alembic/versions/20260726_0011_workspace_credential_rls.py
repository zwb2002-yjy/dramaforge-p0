"""Enforce selected-workspace RLS for encrypted provider credentials.

Revision ID: 20260726_0011
Revises: 20260726_0010
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260726_0011"
down_revision: str | None = "20260726_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE encrypted_provider_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE encrypted_provider_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS encrypted_provider_credentials_workspace_scope "
        "ON encrypted_provider_credentials"
    )
    op.execute(
        """
        CREATE POLICY encrypted_provider_credentials_workspace_scope
        ON encrypted_provider_credentials
        FOR ALL
        USING (
          workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = encrypted_provider_credentials.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
        )
        WITH CHECK (
          workspace_id = app.current_workspace_id()
          AND EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = encrypted_provider_credentials.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS encrypted_provider_credentials_workspace_scope "
        "ON encrypted_provider_credentials"
    )
    op.execute("ALTER TABLE encrypted_provider_credentials NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE encrypted_provider_credentials DISABLE ROW LEVEL SECURITY")
