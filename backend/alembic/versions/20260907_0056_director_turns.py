"""Add bounded Director turns and text invocation evidence.

Revision ID: 20260907_0056
Revises: 20260903_0055
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0056"
down_revision: str | None = "20260903_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_project_rls() -> None:
    op.execute("ALTER TABLE director_turns ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE director_turns FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS director_turns_project_scope ON director_turns")
    op.execute(
        """
        CREATE POLICY director_turns_project_scope ON director_turns
        FOR ALL
        USING (project_id = app.current_project_id())
        WITH CHECK (project_id = app.current_project_id())
        """
    )


def _disable_project_rls() -> None:
    op.execute("DROP POLICY IF EXISTS director_turns_project_scope ON director_turns")
    op.execute("ALTER TABLE director_turns NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE director_turns DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table(
        "director_turns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(24), nullable=False),
        sa.Column("scope_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_key", sa.String(200), nullable=False),
        sa.Column("context_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "input_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "intent_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_resolution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("transport_record_id", sa.String(200), nullable=True),
        sa.Column("transport_status", sa.String(32), nullable=False, server_default="created"),
        sa.Column(
            "request_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "token_usage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("provider_cost", sa.Numeric(20, 8), nullable=True),
        sa.Column("cost_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="USD"),
        sa.Column("output_hash", sa.CHAR(64), nullable=True),
        sa.Column(
            "output_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("wait_reason", sa.String(80), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dispatched_command_key", sa.String(200), nullable=True),
        sa.Column(
            "node_run_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_repair_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposal_id"], ["director_proposals.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_director_turn_request"),
        sa.CheckConstraint("revision > 0", name="ck_director_turn_revision_positive"),
        sa.CheckConstraint("step_count >= 0", name="ck_director_turn_step_count_nonnegative"),
        sa.CheckConstraint(
            "schema_repair_count >= 0 AND schema_repair_count <= 1",
            name="ck_director_turn_schema_repair_bounded",
        ),
        sa.CheckConstraint(
            "status IN ('queued','thinking','awaiting_user','awaiting_execution',"
            "'completed','failed','cancelled','stale')",
            name="ck_director_turn_status",
        ),
        sa.CheckConstraint(
            "cost_status IN ('unknown','reported')", name="ck_director_turn_cost_status"
        ),
    )
    op.create_index(
        "ix_director_turns_scope",
        "director_turns",
        ["project_id", "scope_type", "scope_entity_id"],
    )
    op.create_index(
        "ix_director_turns_status",
        "director_turns",
        ["project_id", "status", "updated_at"],
    )
    _enable_project_rls()


def downgrade() -> None:
    _disable_project_rls()
    op.drop_index("ix_director_turns_status", table_name="director_turns")
    op.drop_index("ix_director_turns_scope", table_name="director_turns")
    op.drop_table("director_turns")
