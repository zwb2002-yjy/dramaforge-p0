"""Published research analysis manifests, invocation links and result links (I4-02).

An analysis row exists only after a completed run published its six category outcomes,
coverage and manifest; invocations and research revisions are linked immutably. The
file revision gains a forward-only ``current_analysis_id`` pointer. No analysis job
table is created: waiting/failed work stays in the original Turn/Flow facts.

Revision ID: 20261118_0111
Revises: 20261118_0110
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261118_0111"
down_revision: str | None = "20261118_0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
        "USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )


def _append_only(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT ON {table} TO dramaforge_app")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM dramaforge_app")


def upgrade() -> None:
    op.create_table(
        "research_analyses",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("file_revision_id", sa.UUID(), nullable=False),
        sa.Column("source_extraction_id", sa.UUID(), nullable=False),
        sa.Column("coverage", postgresql.JSONB(), nullable=False),
        sa.Column("category_outcomes", postgresql.JSONB(), nullable=False),
        sa.Column("manifest_hash", sa.CHAR(64), nullable=False),
        sa.Column("request_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("project_id", "request_key", name="uq_research_analysis_request"),
        sa.UniqueConstraint(
            "id", "file_revision_id", "project_id",
            name="uq_research_analysis_revision_scope",
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_research_analysis_scope"),
        sa.ForeignKeyConstraint(
            ["source_extraction_id", "file_revision_id", "project_id"],
            [
                "source_extractions.id",
                "source_extractions.file_revision_id",
                "source_extractions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_analysis_extraction",
            deferrable=True, initially="DEFERRED",
        ),
    )
    op.create_index(
        "ix_research_analysis_revision",
        "research_analyses",
        ["project_id", "file_revision_id", "completed_at", "id"],
    )

    op.create_table(
        "research_analysis_invocations",
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("invocation_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "analysis_id", "invocation_id", name="pk_research_analysis_invocation",
        ),
        sa.UniqueConstraint(
            "analysis_id", "ordinal", name="uq_research_analysis_invocation_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id", "project_id"],
            ["research_analyses.id", "research_analyses.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_invocation_analysis",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["invocation_id", "project_id"],
            ["director_invocations.id", "director_invocations.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_invocation_invocation",
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_research_analysis_invocation_ordinal"),
    )

    op.create_table(
        "research_analysis_results",
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("research_revision_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "analysis_id", "research_revision_id", name="pk_research_analysis_result",
        ),
        sa.UniqueConstraint(
            "analysis_id", "category", "ordinal", name="uq_research_analysis_result_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id", "project_id"],
            ["research_analyses.id", "research_analyses.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_result_analysis",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["research_revision_id", "project_id"],
            ["research_result_revisions.id", "research_result_revisions.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_result_revision",
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "category IN ('summary','person','place','event','timeline','cultural_clue')",
            name="ck_research_analysis_result_category",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_research_analysis_result_ordinal"),
    )

    op.add_column(
        "project_file_revisions", sa.Column("current_analysis_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_file_revision_current_analysis",
        "project_file_revisions",
        "research_analyses",
        ["current_analysis_id", "id", "project_id"],
        ["id", "file_revision_id", "project_id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )

    for table in (
        "research_analyses",
        "research_analysis_invocations",
        "research_analysis_results",
    ):
        _rls(table)
        _append_only(table)


def downgrade() -> None:
    op.drop_constraint(
        "fk_project_file_revision_current_analysis",
        "project_file_revisions",
        type_="foreignkey",
    )
    op.drop_column("project_file_revisions", "current_analysis_id")
    for table in (
        "research_analysis_results",
        "research_analysis_invocations",
        "research_analyses",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_table("research_analysis_results")
    op.drop_table("research_analysis_invocations")
    op.drop_table("research_analyses")
