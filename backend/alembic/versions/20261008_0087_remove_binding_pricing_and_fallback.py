"""Remove non-authoritative binding pricing and fake fallback policy.

Catalog pricing may remain informational metadata. Production execution no
longer derives any execution fact from workspace-entered pricing, and project
provider bindings have one explicit selection path with no fallback strategy.
Historical ProviderOperation currency/cost receipts are preserved.
"""

from alembic import op

revision = "20261008_0087"
down_revision = "20261008_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("provider_model_bindings", "pricing_snapshot_json")
    op.drop_column("project_provider_bindings", "fallback_policy")


def downgrade() -> None:
    raise RuntimeError(
        "Binding pricing/fallback were removed as non-authoritative product state; "
        "restore a database snapshot to downgrade"
    )
