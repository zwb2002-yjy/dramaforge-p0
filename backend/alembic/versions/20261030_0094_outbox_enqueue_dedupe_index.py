"""Serve the enqueue dedupe lookup from an index instead of a project scan."""

from alembic import op

revision = "20261030_0094"
down_revision = "20261030_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The scheduler asks "is there already a node_run.enqueue fact for this run
    # and dispatch generation?".  The partial expression index answers that
    # without loading a project's whole enqueue history into Python.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_outbox_events_node_run_enqueue
        ON public.outbox_events (
            project_id,
            (payload->>'node_run_id'),
            (payload->>'dispatch_generation')
        )
        WHERE topic = 'node_run.enqueue'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_outbox_events_node_run_enqueue")
