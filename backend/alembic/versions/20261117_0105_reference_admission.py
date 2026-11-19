"""Reference grants freeze the egress admission that allowed them (I3-02).

A public artifact reference lets an external provider fetch private project
bytes, so the admission decision is part of the grant's own evidence. Existing
grants keep NULL (they predate the field and are never rewritten); new grants
always record the decision, allowed or refused at a later read.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261117_0105"
down_revision = "20261117_0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "artifact_reference_tokens",
        sa.Column("egress_admission", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("artifact_reference_tokens", "egress_admission")
