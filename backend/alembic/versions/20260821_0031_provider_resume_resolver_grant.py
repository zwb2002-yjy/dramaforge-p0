"""Grant the Worker resolver read access to Provider resume facts.

Revision ID: 20260821_0031
Revises: 20260821_0030
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0031"
down_revision: str | None = "20260821_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON provider_operations TO dramaforge_worker_resolver")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON provider_operations FROM dramaforge_worker_resolver")
