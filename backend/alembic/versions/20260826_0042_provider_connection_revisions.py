"""Freeze immutable ProviderConnection execution revisions.

Revision ID: 20260826_0042
Revises: 20260826_0041
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0042"
down_revision: str | None = "20260826_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "provider_connection_revisions"
_OPERATION_FK = "fk_provider_operations_connection_revision"
_OPERATION_INDEX = "ix_provider_operations_connection_revision_id"
_REVISION_UNIQUE = "uq_provider_connection_revision_no"
_REVISION_FK = "fk_provider_connection_revision_connection"
_CREDENTIAL_FK = "fk_provider_connection_revision_credential"


def _revision_rls() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_TABLE}_workspace_scope ON {_TABLE}
        FOR ALL
        USING (
          EXISTS (
            SELECT 1
            FROM provider_connections c
            JOIN workspaces w ON w.id = c.workspace_id
            WHERE c.id = {_TABLE}.connection_id
              AND c.workspace_id = app.current_workspace_id()
              AND w.owner_user_id = app.current_user_id()
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1
            FROM provider_connections c
            JOIN workspaces w ON w.id = c.workspace_id
            WHERE c.id = {_TABLE}.connection_id
              AND c.workspace_id = app.current_workspace_id()
              AND w.owner_user_id = app.current_user_id()
          )
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("provider_type", sa.String(40), nullable=False),
        sa.Column("protocol_profile", sa.String(80), nullable=False),
        sa.Column("base_url", sa.String(240), nullable=False),
        sa.Column("credential_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["provider_connections.id"],
            name=_REVISION_FK,
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_revision_id"],
            ["encrypted_provider_credentials.id"],
            name=_CREDENTIAL_FK,
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("connection_id", "revision_no", name=_REVISION_UNIQUE),
        sa.CheckConstraint(
            "revision_no > 0",
            name="ck_provider_connection_revision_positive",
        ),
    )
    op.create_index(
        "ix_provider_connection_revisions_connection_id",
        _TABLE,
        ["connection_id"],
    )
    op.execute(
        f"""
        INSERT INTO {_TABLE}
          (id, connection_id, revision_no, provider_type, protocol_profile,
           base_url, credential_revision_id, created_at)
        SELECT
          gen_random_uuid(), c.id, 1, c.provider_type, c.protocol_profile,
          c.base_url, c.credential_id, c.created_at
        FROM provider_connections c
        """
    )
    op.add_column(
        "provider_operations",
        sa.Column(
            "provider_connection_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        _OPERATION_INDEX,
        "provider_operations",
        ["provider_connection_revision_id"],
    )
    op.create_foreign_key(
        _OPERATION_FK,
        "provider_operations",
        _TABLE,
        ["provider_connection_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    _revision_rls()


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_workspace_scope ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_constraint(_OPERATION_FK, "provider_operations", type_="foreignkey")
    op.drop_index(_OPERATION_INDEX, table_name="provider_operations")
    op.drop_column("provider_operations", "provider_connection_revision_id")
    op.drop_index("ix_provider_connection_revisions_connection_id", table_name=_TABLE)
    op.drop_table(_TABLE)
