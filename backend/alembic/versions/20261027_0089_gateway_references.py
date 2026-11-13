"""Non-secret Proxy references on existing connections and immutable revisions."""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0089"
down_revision = "20261024_0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_connections", sa.Column("gateway_ref", sa.JSON(), nullable=True))
    op.add_column(
        "provider_connection_revisions", sa.Column("gateway_ref", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("GATEWAY_REFERENCE_DOWNGRADE_REQUIRES_DATA_INSPECTION")
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "LOCK TABLE provider_connections, provider_connection_revisions IN ACCESS EXCLUSIVE MODE"
            )
        )
    for table in ("provider_connections", "provider_connection_revisions"):
        existing = op.get_bind().scalar(
            sa.text(
                f"SELECT 1 FROM {table} WHERE gateway_ref IS NOT NULL "
                "AND CAST(gateway_ref AS TEXT) <> 'null' LIMIT 1"
            )
        )
        if existing is not None:
            raise RuntimeError(
                "GATEWAY_REFERENCE_DOWNGRADE_BLOCKED: retain schema and restore a verified snapshot"
            )
    op.drop_column("provider_connection_revisions", "gateway_ref")
    op.drop_column("provider_connections", "gateway_ref")
