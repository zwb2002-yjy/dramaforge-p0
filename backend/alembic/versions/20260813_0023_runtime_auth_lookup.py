"""Add a least-privilege authentication lookup for the runtime role.

Revision ID: 20260813_0023
Revises: 20260813_0022
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_0023"
down_revision: str | None = "20260813_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.auth_user_by_email(p_email text)
        RETURNS TABLE (
          id uuid,
          email varchar(320),
          display_name varchar(120),
          password_hash text,
          is_active boolean,
          created_at timestamptz,
          updated_at timestamptz,
          version integer
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
          SELECT
            u.id,
            u.email,
            u.display_name,
            u.password_hash,
            u.is_active,
            u.created_at,
            u.updated_at,
            u.version
          FROM public.users AS u
          WHERE u.email = lower(p_email)
          LIMIT 1
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.auth_user_by_email(text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.auth_user_by_email(text) "
        "TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.auth_user_by_email(text)")
