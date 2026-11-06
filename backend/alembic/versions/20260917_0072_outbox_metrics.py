"""Expose process-wide pending Outbox metrics without bypassing RLS in callers."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0072"
down_revision: str | None = "20260917_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.outbox_metrics()
        RETURNS TABLE(pending_count bigint, oldest_created_at timestamptz)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT count(*)::bigint, min(created_at)
          FROM outbox_events
          WHERE status = 'pending'
        $$
        """
    )
    op.execute("ALTER FUNCTION app.outbox_metrics() OWNER TO dramaforge_worker_resolver")
    op.execute("REVOKE ALL ON FUNCTION app.outbox_metrics() FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.outbox_metrics() TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.outbox_metrics()")
