"""Human review decisions: the fact that lets an Artifact continue production."""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0068"
down_revision = "20260915_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "human_review_decisions",
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
            "artifact_id",
            sa.UUID(),
            sa.ForeignKey("artifacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "review_node_run_id",
            sa.UUID(),
            sa.ForeignKey("node_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "review_artifact_id",
            sa.UUID(),
            sa.ForeignKey("artifacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("review_kind", sa.String(32), nullable=False),
        sa.Column("subject_fingerprint", sa.String(64), nullable=False),
        sa.Column("shot_version_at_decision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "supersedes_id",
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
        sa.UniqueConstraint(
            "project_id", "request_key", name="uq_human_review_decision_request"
        ),
        sa.CheckConstraint(
            "decision IN ('approved','rejected')", name="ck_human_review_decision_value"
        ),
    )
    op.create_index(
        "ix_human_review_decisions_lookup",
        "human_review_decisions",
        ["project_id", "shot_id", "artifact_id", "review_kind"],
    )
    op.execute("ALTER TABLE human_review_decisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE human_review_decisions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY human_review_decisions_scope ON human_review_decisions FOR ALL "
        "USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON human_review_decisions TO dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS human_review_decisions_scope ON human_review_decisions")
    op.drop_index("ix_human_review_decisions_lookup", table_name="human_review_decisions")
    op.drop_table("human_review_decisions")
