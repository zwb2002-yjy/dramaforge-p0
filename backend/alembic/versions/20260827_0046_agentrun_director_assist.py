"""AgentRun director_assist compatibility (Phase 7 P7-01).

- Adds ``director_assist`` to the native ``agent_operation`` enum.
- Makes ``agent_runs.planning_authorization_id`` nullable so the new Director
  Assistant path does not require a Budget/Planning authorization, while the
  legacy path keeps requiring one.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260827_0046"
down_revision: str | None = "20260827_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE agent_operation ADD VALUE IF NOT EXISTS 'director_assist'"
    )
    op.execute(
        "ALTER TABLE agent_runs ALTER COLUMN planning_authorization_id DROP NOT NULL"
    )


def downgrade() -> None:
    # PG cannot remove an enum value easily; revert the column only and leave
    # the additive enum value in place (safe for future re-apply).
    op.execute(
        "ALTER TABLE agent_runs ALTER COLUMN planning_authorization_id SET NOT NULL"
    )
