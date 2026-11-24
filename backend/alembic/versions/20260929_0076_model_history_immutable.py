"""Protect model capability and provider evidence history from mutation.

Revision ID: 20260929_0076
Revises: 20260929_0075
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260929_0076"
down_revision: str | None = "20260929_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HISTORY_TABLES = (
    "model_capability_revisions",
    "model_publication_events",
    "connection_discovered_models",
    "connection_model_capability_revisions",
    "provider_availability_evidence",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.reject_model_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'model and provider evidence history is immutable';
        END $$
        """
    )
    for table in _HISTORY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_model_history_mutation()"
        )


def downgrade() -> None:
    for table in reversed(_HISTORY_TABLES):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION app.reject_model_history_mutation()")
