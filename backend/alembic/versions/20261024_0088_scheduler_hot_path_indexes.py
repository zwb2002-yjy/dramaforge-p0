"""Scheduler hot-path indexes (backend-review 1.2 / V8 evidence).

EXPLAIN ANALYZE on a seeded database (201k outbox rows, 50k node_runs, 44k
director_wakeups) measured the dispatcher claim at a 35ms parallel seq scan
running every second and the director wakeup scan at a 2.8ms seq scan every
five seconds, both growing linearly with accumulated terminal rows. The
three partial indexes keep each scan proportional to its live working set:

- outbox_events(status, next_attempt_at) WHERE status <> 'published':
  claim, pending metrics and lease reclaim read only unpublished rows.
- director_wakeups(next_attempt_at, inbox_id) WHERE completed_at IS NULL
  AND dead_letter_at IS NULL: the due-wakeup scan skips completed history.
- node_runs(created_at, id) WHERE status = 'queued': the scheduler claim
  reads rows in arrival order without a sort and without scanning history.
"""

from alembic import op
from sqlalchemy import text

revision = "20261024_0088"
down_revision = "20261008_0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_outbox_events_unpublished",
        "outbox_events",
        ["status", "next_attempt_at"],
        postgresql_where=text("status <> 'published'"),
        sqlite_where=text("status <> 'published'"),
    )
    op.create_index(
        "idx_director_wakeups_due",
        "director_wakeups",
        ["next_attempt_at", "inbox_id"],
        postgresql_where=text("completed_at IS NULL AND dead_letter_at IS NULL"),
        sqlite_where=text("completed_at IS NULL AND dead_letter_at IS NULL"),
    )
    op.create_index(
        "idx_node_runs_queued_order",
        "node_runs",
        ["created_at", "id"],
        postgresql_where=text("status = 'queued'"),
        sqlite_where=text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("idx_node_runs_queued_order", table_name="node_runs")
    op.drop_index("idx_director_wakeups_due", table_name="director_wakeups")
    op.drop_index("idx_outbox_events_unpublished", table_name="outbox_events")
