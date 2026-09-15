"""Persist exact user-approved commands before director submission."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260909_0061"
down_revision = "20260908_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_command_authorizations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("shot_id", sa.UUID(), sa.ForeignKey("shots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("node_run_id", sa.UUID(), sa.ForeignKey("node_runs.id", ondelete="RESTRICT")),
        sa.UniqueConstraint("project_id", "command_key", name="uq_production_authorized_command"),
        sa.CheckConstraint("status IN ('approved','accepted','revoked')", name="ck_command_auth_status"),
        sa.CheckConstraint("profile_version > 0", name="ck_command_auth_profile_version"),
        sa.CheckConstraint(
            "(status = 'accepted' AND node_run_id IS NOT NULL) OR "
            "(status <> 'accepted' AND node_run_id IS NULL)",
            name="ck_command_auth_receipt",
        ),
    )
    op.execute("ALTER TABLE production_command_authorizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE production_command_authorizations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY production_command_authorizations_scope
        ON production_command_authorizations FOR ALL
        USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON production_command_authorizations TO dramaforge_app")


def downgrade() -> None:
    op.drop_table("production_command_authorizations")
