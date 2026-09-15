"""Record the transport-retry identity of an asset creation submission."""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0067"
down_revision = "20260910_0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("creation_request_key", sa.String(160), nullable=True))
    op.add_column("assets", sa.Column("creation_request_hash", sa.String(64), nullable=True))
    # Partial unique index: pre-existing cards and explicit new operations carry
    # no key, so they are not constrained.
    op.create_index(
        "uq_assets_project_creation_request",
        "assets",
        ["project_id", "creation_request_key"],
        unique=True,
        postgresql_where=sa.text("creation_request_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_assets_project_creation_request", table_name="assets")
    op.drop_column("assets", "creation_request_hash")
    op.drop_column("assets", "creation_request_key")
