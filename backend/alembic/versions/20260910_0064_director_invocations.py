"""Persist individual director text invocation identities and validated outputs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260910_0064"
down_revision = "20260910_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_director_turn_scope", "director_turns", ["id", "project_id"])
    op.create_table(
        "director_invocations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("invocation_key", sa.String(200), nullable=False),
        sa.Column("step_key", sa.String(160), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("model_resolution", postgresql.JSONB(), nullable=False),
        sa.Column("request_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("output_schema", postgresql.JSONB(), nullable=False),
        sa.Column("intent_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("validated_output", postgresql.JSONB(), nullable=True),
        sa.Column("output_hash", sa.String(64)),
        sa.Column("token_usage", postgresql.JSONB(), nullable=False),
        sa.Column("reported_cost", sa.Numeric(20, 8)),
        sa.Column("cost_status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(120)),
        sa.Column("response_summary", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("submission_started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["turn_id", "project_id"], ["director_turns.id", "director_turns.project_id"],
            ondelete="CASCADE", name="fk_director_invocation_turn_scope",
        ),
        sa.UniqueConstraint("turn_id", "invocation_key", name="uq_director_invocation_key"),
        sa.CheckConstraint("attempt > 0", name="ck_director_invocation_attempt"),
        sa.CheckConstraint(
            "status IN ('prepared','submission_started','completed','failed','unknown_submission')",
            name="ck_director_invocation_status",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND output_hash IS NOT NULL AND validated_output IS NOT NULL) "
            "OR (status <> 'completed' AND output_hash IS NULL AND validated_output IS NULL)",
            name="ck_director_invocation_output",
        ),
        sa.CheckConstraint(
            "(cost_status = 'unknown' AND reported_cost IS NULL) OR "
            "(cost_status = 'reported' AND reported_cost IS NOT NULL AND reported_cost >= 0)",
            name="ck_director_invocation_cost",
        ),
    )
    op.execute("ALTER TABLE director_invocations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE director_invocations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY director_invocations_scope ON director_invocations FOR ALL
        USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON director_invocations TO dramaforge_app")


def downgrade() -> None:
    op.drop_table("director_invocations")
    op.drop_constraint("uq_director_turn_scope", "director_turns", type_="unique")
