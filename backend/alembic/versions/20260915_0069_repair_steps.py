"""Record confirmed repair intents and their staged actions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_0069"
down_revision = "20260915_0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repair_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shot_id", sa.UUID(), sa.ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("option", sa.String(40), nullable=False),
        sa.Column("plan_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("plan_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "annotation_ids",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "annotation_summary",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_formal_artifact_id",
            sa.UUID(),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("input_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("closed_reason", sa.String(120), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "request_key", name="uq_repair_request_key"),
        sa.CheckConstraint(
            "option IN ('rerun_video','regenerate_keyframe_then_video')",
            name="ck_repair_request_option",
        ),
    )
    op.create_table(
        "repair_steps",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "repair_request_id",
            sa.UUID(),
            sa.ForeignKey("repair_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("plan_fingerprint", sa.CHAR(64), nullable=True),
        sa.Column("command_key", sa.String(200), nullable=True),
        sa.Column(
            "node_run_id",
            sa.UUID(),
            sa.ForeignKey("node_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "confirmed_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "adopted_artifact_id",
            sa.UUID(),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "review_decision_id",
            sa.UUID(),
            sa.ForeignKey("human_review_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("repair_request_id", "ordinal", name="uq_repair_step_ordinal"),
    )
    op.create_index(
        "idx_repair_requests_project_shot",
        "repair_requests",
        ["project_id", "shot_id", "created_at"],
    )
    op.create_index(
        "idx_repair_steps_request",
        "repair_steps",
        ["repair_request_id", "ordinal"],
    )
    for table in ("repair_requests", "repair_steps"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_scope ON {table} FOR ALL "
            "USING (project_id = app.current_project_id()) "
            "WITH CHECK (project_id = app.current_project_id())"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dramaforge_app")


def downgrade() -> None:
    for table in ("repair_steps", "repair_requests"):
        op.execute(f"DROP POLICY IF EXISTS {table}_scope ON {table}")
    op.drop_index("idx_repair_steps_request", table_name="repair_steps")
    op.drop_index("idx_repair_requests_project_shot", table_name="repair_requests")
    op.drop_table("repair_steps")
    op.drop_table("repair_requests")
