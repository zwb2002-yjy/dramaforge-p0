"""Explicit no-auth media connections; preserve all bearer revision identities."""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0090"
down_revision = "20261027_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("provider_availability_evidence", "provider_model_availability"):
        op.alter_column(table, "credential_revision_id", existing_type=sa.Uuid(), nullable=True)
    op.drop_constraint(
        "uq_provider_model_availability_identity", "provider_model_availability", type_="unique"
    )
    op.create_unique_constraint(
        "uq_provider_model_availability_identity",
        "provider_model_availability",
        ["connection_revision_id", "credential_revision_id", "remote_model_id"],
        postgresql_nulls_not_distinct=True,
    )
    for table, column in (
        ("provider_connections", "credential_id"),
        ("provider_connection_revisions", "credential_revision_id"),
    ):
        op.add_column(
            table, sa.Column("auth_mode", sa.String(20), nullable=False, server_default="bearer")
        )
        op.alter_column(table, column, existing_type=sa.Uuid(), nullable=True)
        op.create_check_constraint(
            "ck_" + table + "_auth_mode",
            table,
            "(auth_mode = 'bearer' AND " + column + " IS NOT NULL) OR "
            "(auth_mode = 'none' AND " + column + " IS NULL AND "
            "provider_type = 'openai_compatible_media')",
        )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("MEDIA_AUTH_DOWNGRADE_REQUIRES_INSPECTION")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE provider_connections, provider_connection_revisions, provider_availability_evidence, provider_model_availability IN ACCESS EXCLUSIVE MODE"
        )
    )
    for table in ("provider_availability_evidence", "provider_model_availability"):
        if bind.scalar(
            sa.text("SELECT 1 FROM " + table + " WHERE credential_revision_id IS NULL LIMIT 1")
        ):
            raise RuntimeError("MEDIA_AUTH_DOWNGRADE_BLOCKED: retain no-auth availability evidence")
    for table in ("provider_connections", "provider_connection_revisions"):
        if bind.scalar(sa.text("SELECT 1 FROM " + table + " WHERE auth_mode <> 'bearer' LIMIT 1")):
            raise RuntimeError("MEDIA_AUTH_DOWNGRADE_BLOCKED: retain no-auth historical revisions")
    for table, column in (
        ("provider_connection_revisions", "credential_revision_id"),
        ("provider_connections", "credential_id"),
    ):
        op.drop_constraint("ck_" + table + "_auth_mode", table, type_="check")
        op.alter_column(table, column, existing_type=sa.Uuid(), nullable=False)
        op.drop_column(table, "auth_mode")
    op.drop_constraint(
        "uq_provider_model_availability_identity", "provider_model_availability", type_="unique"
    )
    op.create_unique_constraint(
        "uq_provider_model_availability_identity",
        "provider_model_availability",
        ["connection_revision_id", "credential_revision_id", "remote_model_id"],
    )
    for table in ("provider_availability_evidence", "provider_model_availability"):
        op.alter_column(table, "credential_revision_id", existing_type=sa.Uuid(), nullable=False)
