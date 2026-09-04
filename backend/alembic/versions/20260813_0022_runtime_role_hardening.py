"""Remove the historical public runtime-role password and refresh grants.

Revision ID: 20260813_0022
Revises: 20260813_0021

The release Compose bootstrap injects a unique password after migrations.  The
migration only owns schema privileges and deliberately leaves the role unable
to log in until the operator-controlled bootstrap step sets that password.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_0022"
down_revision: str | None = "20260813_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER ROLE dramaforge_app NOLOGIN NOINHERIT NOBYPASSRLS PASSWORD NULL")
    op.execute("GRANT USAGE ON SCHEMA public, app TO dramaforge_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "TO dramaforge_app"
    )
    # The frozen provider catalog is globally readable but migration-owned.
    op.execute("GRANT SELECT ON provider_model_catalog_entries TO dramaforge_app")
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE ON provider_model_catalog_entries "
        "FROM dramaforge_app"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dramaforge_app"
    )
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO dramaforge_app")


def downgrade() -> None:
    # Never recreate the historical public password.  A rollback keeps the
    # role disabled until an operator assigns a fresh secret again.
    op.execute("ALTER ROLE dramaforge_app NOLOGIN NOINHERIT NOBYPASSRLS PASSWORD NULL")
