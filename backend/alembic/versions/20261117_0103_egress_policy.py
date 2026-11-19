"""Trusted provider destinations and project egress policy (M03 part 1).

Destinations are immutable declarations about already-registered bindings; policy
revisions are immutable permission sets with one mutable head per project. Both
revision tables are append-only for the runtime role; the schema-wide default
privileges grant every verb on new tables, so the write verbs are revoked
explicitly. The head points back at its revision, so that FK is added last.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20261117_0103"
down_revision = "20261117_0102"
branch_labels = None
depends_on = None


def _rls_project(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
        "USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )


def upgrade() -> None:
    op.create_table(
        "provider_destination_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey(
            "workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("binding_ref", sa.String(200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("origin_expected_revision", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("upstream_origin", sa.Text(), nullable=False),
        sa.Column("processing_location", sa.String(16), nullable=False),
        sa.Column("purposes", postgresql.JSONB(), nullable=False),
        sa.Column("declaration_hash", sa.CHAR(64), nullable=False),
        sa.Column("configuration_hash", sa.CHAR(64), nullable=False),
        sa.Column("route_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("location_evidence", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint(
            "workspace_id", "binding_ref", "revision", name="uq_destination_binding_revision",
        ),
        sa.UniqueConstraint(
            "workspace_id", "binding_ref", "origin_expected_revision",
            name="uq_destination_binding_origin",
        ),
        sa.UniqueConstraint("id", "workspace_id", name="uq_destination_workspace_scope"),
        sa.CheckConstraint("revision > 0", name="ck_destination_revision"),
        sa.CheckConstraint("origin_expected_revision >= 0", name="ck_destination_origin_revision"),
        sa.CheckConstraint(
            "processing_location IN ('local','external','unknown')",
            name="ck_destination_location",
        ),
    )
    op.create_index(
        "ix_destination_binding", "provider_destination_revisions",
        ["workspace_id", "binding_ref", "revision"],
    )

    op.create_table(
        "project_egress_policy_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("origin_expected_revision", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("policy_data", postgresql.JSONB(), nullable=False),
        sa.Column("policy_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "revision", name="uq_egress_policy_revision"),
        sa.UniqueConstraint(
            "project_id", "origin_expected_revision", name="uq_egress_policy_origin",
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_egress_policy_scope"),
        sa.CheckConstraint("revision > 0", name="ck_egress_policy_revision"),
        sa.CheckConstraint("origin_expected_revision >= 0", name="ck_egress_policy_origin"),
        sa.CheckConstraint(
            "mode IN ('current','local_only','allowlisted')", name="ck_egress_policy_mode",
        ),
    )
    op.create_index(
        "ix_egress_policy_project", "project_egress_policy_revisions",
        ["project_id", "revision"],
    )

    op.create_table(
        "project_egress_policy_heads",
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("current_revision_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_egress_head_revision"),
    )
    op.create_foreign_key(
        "fk_egress_head_revision",
        "project_egress_policy_heads", "project_egress_policy_revisions",
        ["current_revision_id", "project_id"], ["id", "project_id"],
        ondelete="NO ACTION", deferrable=True, initially="DEFERRED",
    )

    _rls_project("project_egress_policy_revisions")
    _rls_project("project_egress_policy_heads")

    # The Workspace is the discovery boundary for destinations.
    op.execute("ALTER TABLE provider_destination_revisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE provider_destination_revisions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY provider_destination_revisions_workspace_scope "
        "ON provider_destination_revisions FOR ALL "
        "USING (EXISTS (SELECT 1 FROM workspaces w WHERE w.id = workspace_id "
        "AND w.owner_user_id = app.current_user_id())) "
        "WITH CHECK (EXISTS (SELECT 1 FROM workspaces w WHERE w.id = workspace_id "
        "AND w.owner_user_id = app.current_user_id()))"
    )

    op.execute(
        "GRANT SELECT, INSERT ON provider_destination_revisions TO dramaforge_app"
    )
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON provider_destination_revisions "
        "FROM dramaforge_app"
    )
    op.execute(
        "GRANT SELECT, INSERT ON project_egress_policy_revisions TO dramaforge_app"
    )
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON project_egress_policy_revisions "
        "FROM dramaforge_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON project_egress_policy_heads TO dramaforge_app"
    )
    op.execute(
        "REVOKE DELETE, TRUNCATE ON project_egress_policy_heads FROM dramaforge_app"
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("EGRESS_POLICY_DOWNGRADE_REQUIRES_ONLINE_PREFLIGHT")
    connection = op.get_bind()
    populated = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM provider_destination_revisions) "
            "OR EXISTS(SELECT 1 FROM project_egress_policy_revisions)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("EGRESS_POLICY_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE")
    for policy, table in (
        ("provider_destination_revisions_workspace_scope", "provider_destination_revisions"),
        ("project_egress_policy_revisions_project_scope", "project_egress_policy_revisions"),
        ("project_egress_policy_heads_project_scope", "project_egress_policy_heads"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    for table in (
        "project_egress_policy_heads",
        "project_egress_policy_revisions",
        "provider_destination_revisions",
    ):
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_constraint(
        "fk_egress_head_revision", "project_egress_policy_heads", type_="foreignkey",
    )
    op.drop_index("ix_egress_policy_project", table_name="project_egress_policy_revisions")
    op.drop_table("project_egress_policy_heads")
    op.drop_table("project_egress_policy_revisions")
    op.drop_index("ix_destination_binding", table_name="provider_destination_revisions")
    op.drop_table("provider_destination_revisions")
