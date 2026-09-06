"""Create a narrowly privileged maintenance role for BYOK key rotation.

Revision ID: 20260726_0012
Revises: 20260726_0011
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260726_0012"
down_revision: str | None = "20260726_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "dramaforge_byok_rotation"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN
            CREATE ROLE {_ROLE} NOLOGIN NOINHERIT BYPASSRLS;
          END IF;
        END $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE}")
    op.execute(
        f"GRANT SELECT, UPDATE ON encrypted_provider_credentials TO {_ROLE}"
    )
    op.execute(f"GRANT INSERT ON key_rotation_audits TO {_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON key_rotation_audits FROM {_ROLE}")
    op.execute(f"REVOKE ALL ON encrypted_provider_credentials FROM {_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {_ROLE}")
