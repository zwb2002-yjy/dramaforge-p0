"""Add immutable Production-owned policy revisions and separate revocation.

Revision ID: 20260929_0075
Revises: 20260929_0074
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0075"
down_revision: str | None = "20260929_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_policy_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("product_path", sa.String(120), nullable=False),
        sa.Column("allowed_operations_json", sa.JSON(), nullable=False),
        sa.Column("allowed_contracts_json", sa.JSON(), nullable=False),
        sa.Column("allowed_options_json", sa.JSON(), nullable=False),
        sa.Column("constraint_overrides_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("policy_id", "policy_revision", name="uq_product_policy_revision"),
        sa.CheckConstraint("policy_revision > 0", name="ck_product_policy_revision_positive"),
    )
    op.create_table(
        "product_policy_states",
        sa.Column(
            "policy_revision_id",
            sa.UUID(),
            sa.ForeignKey("product_policy_revisions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_product_policy_state_status"),
    )
    op.create_table(
        "product_policy_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "policy_revision_id",
            sa.UUID(),
            sa.ForeignKey("product_policy_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('active','revoked')",
            name="ck_product_policy_event_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('active','revoked')", name="ck_product_policy_event_to_status"
        ),
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_product_policy_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'product policy history is immutable';
        END $$
        """
    )
    for table in ("product_policy_revisions", "product_policy_events"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_product_policy_history_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION app.enforce_product_policy_state_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'product policy revocation is irreversible';
          END IF;
          IF OLD.status <> 'active' OR NEW.status <> 'revoked'
             OR NEW.policy_revision_id <> OLD.policy_revision_id THEN
            RAISE EXCEPTION 'product policy revocation is irreversible';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER product_policy_states_one_way BEFORE UPDATE OR DELETE "
        "ON product_policy_states FOR EACH ROW "
        "EXECUTE FUNCTION app.enforce_product_policy_state_transition()"
    )
    for table in (
        "product_policy_revisions",
        "product_policy_states",
        "product_policy_events",
    ):
        op.execute(f"GRANT SELECT ON {table} TO dramaforge_app")
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM dramaforge_app")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS product_policy_states_one_way ON product_policy_states")
    op.execute("DROP FUNCTION IF EXISTS app.enforce_product_policy_state_transition()")
    for table in ("product_policy_revisions", "product_policy_events"):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION app.reject_product_policy_history_mutation()")
    op.drop_table("product_policy_events")
    op.drop_table("product_policy_states")
    op.drop_table("product_policy_revisions")
