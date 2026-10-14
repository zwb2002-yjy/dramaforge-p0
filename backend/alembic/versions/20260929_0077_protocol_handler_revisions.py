"""Add separate immutable protocol contracts and runtime handler identities.

Revision ID: 20260929_0077
Revises: 20260929_0076
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0077"
down_revision: str | None = "20260929_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "protocol_contract_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("protocol_contract_id", sa.UUID(), nullable=False),
        sa.Column("protocol_revision", sa.Integer(), nullable=False),
        sa.Column("protocol_hash", sa.String(64), nullable=False),
        sa.Column("protocol_profile", sa.String(80), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "protocol_contract_id", "protocol_revision", name="uq_protocol_contract_revision"
        ),
        sa.CheckConstraint("protocol_revision > 0", name="ck_protocol_contract_revision_positive"),
    )
    op.create_table(
        "runtime_handler_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("runtime_handler_id", sa.UUID(), nullable=False),
        sa.Column("handler_revision", sa.Integer(), nullable=False),
        sa.Column("handler_key", sa.String(120), nullable=False),
        sa.Column("implementation_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "runtime_handler_id", "handler_revision", name="uq_runtime_handler_revision"
        ),
        sa.CheckConstraint("handler_revision > 0", name="ck_runtime_handler_revision_positive"),
    )
    for table in ("protocol_contract_revisions", "runtime_handler_revisions"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_model_history_mutation()"
        )
        for role in ("dramaforge", "dramaforge_app"):
            op.execute(f"GRANT SELECT ON {table} TO {role}")
            op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM {role}")
    op.create_foreign_key(
        "fk_discovered_model_protocol_contract_revision",
        "connection_discovered_models",
        "protocol_contract_revisions",
        ["protocol_contract_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_connection_capability_protocol_contract_revision",
        "connection_model_capability_revisions",
        "protocol_contract_revisions",
        ["protocol_contract_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_connection_capability_protocol_contract_revision",
        "connection_model_capability_revisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_discovered_model_protocol_contract_revision",
        "connection_discovered_models",
        type_="foreignkey",
    )
    for table in ("runtime_handler_revisions", "protocol_contract_revisions"):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
        op.drop_table(table)
