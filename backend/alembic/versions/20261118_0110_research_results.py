"""Research results, immutable revisions, citations and the current-pointer guard (I4-02).

Three project-scoped tables: a stable result, its append-only revisions and the verbatim
citations of each revision. The only mutable fact is the result's current pointer and
version; a trigger refuses to point at an unapplied/foreign/mismatched revision and
advances the version by exactly one. Revisions and citations are append-only for the
application role. No search projection or model invocation is added here.

Revision ID: 20261118_0110
Revises: 20261118_0109
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261118_0110"
down_revision: str | None = "20261118_0109"
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
    # Parent candidate key for the model-origin invocation FK (director_invocations
    # already carries project_id; only the unique pair was missing).
    op.create_unique_constraint(
        "uq_director_invocation_scope", "director_invocations", ["id", "project_id"],
    )

    op.create_table(
        "research_results",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id", sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("current_revision_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_research_result_scope"),
        sa.CheckConstraint(
            "kind IN ('summary','person','place','event','timeline','cultural_clue')",
            name="ck_research_result_kind",
        ),
        sa.CheckConstraint("version > 0", name="ck_research_result_version"),
    )
    op.create_index(
        "ix_research_result_project",
        "research_results",
        ["project_id", "kind", "archived_at", "id"],
    )

    op.create_table(
        "research_result_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("result_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("verification", sa.String(length=16), nullable=False, server_default="unverified"),
        sa.Column("base_revision_id", sa.UUID(), nullable=True),
        sa.Column("restores_revision_id", sa.UUID(), nullable=True),
        sa.Column("accepts_revision_id", sa.UUID(), nullable=True),
        sa.Column("applied_result_version", sa.Integer(), nullable=True),
        sa.Column("origin_invocation_id", sa.UUID(), nullable=True),
        sa.Column("output_item_key", sa.String(length=120), nullable=True),
        sa.Column("request_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("result_id", "number", name="uq_research_revision_number"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_research_revision_request"),
        sa.UniqueConstraint("id", "result_id", "project_id", name="uq_research_revision_scope"),
        sa.UniqueConstraint("id", "project_id", name="uq_research_revision_project"),
        sa.UniqueConstraint(
            "result_id", "applied_result_version", name="uq_research_revision_applied",
        ),
        sa.UniqueConstraint(
            "id", "result_id", "project_id", "applied_result_version",
            name="uq_research_revision_applied_scope",
        ),
        sa.ForeignKeyConstraint(
            ["result_id", "project_id"],
            ["research_results.id", "research_results.project_id"],
            ondelete="RESTRICT", name="fk_research_revision_result",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["base_revision_id", "result_id", "project_id"],
            [
                "research_result_revisions.id",
                "research_result_revisions.result_id",
                "research_result_revisions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_revision_base",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["restores_revision_id", "result_id", "project_id"],
            [
                "research_result_revisions.id",
                "research_result_revisions.result_id",
                "research_result_revisions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_revision_restores",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["accepts_revision_id", "result_id", "project_id"],
            [
                "research_result_revisions.id",
                "research_result_revisions.result_id",
                "research_result_revisions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_revision_accepts",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["origin_invocation_id", "project_id"],
            ["director_invocations.id", "director_invocations.project_id"],
            ondelete="RESTRICT", name="fk_research_revision_invocation",
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint("number > 0", name="ck_research_revision_number"),
        sa.CheckConstraint(
            "origin IN ('user','model','restore','accept')", name="ck_research_revision_origin",
        ),
        sa.CheckConstraint(
            "verification IN ('unverified','corroborated','user_asserted')",
            name="ck_research_revision_verification",
        ),
        sa.CheckConstraint(
            "applied_result_version IS NULL OR applied_result_version > 1",
            name="ck_research_revision_applied_version",
        ),
        sa.CheckConstraint(
            "(origin = 'model' AND origin_invocation_id IS NOT NULL "
            "AND output_item_key IS NOT NULL) "
            "OR (origin <> 'model' AND origin_invocation_id IS NULL "
            "AND output_item_key IS NULL)",
            name="ck_research_revision_invocation_origin",
        ),
        sa.CheckConstraint(
            "(origin = 'restore' AND restores_revision_id IS NOT NULL) "
            "OR (origin <> 'restore' AND restores_revision_id IS NULL)",
            name="ck_research_revision_restores_origin",
        ),
        sa.CheckConstraint(
            "(origin = 'accept' AND accepts_revision_id IS NOT NULL) "
            "OR (origin <> 'accept' AND accepts_revision_id IS NULL)",
            name="ck_research_revision_accepts_origin",
        ),
    )
    op.create_index(
        "ix_research_revision_result",
        "research_result_revisions",
        ["project_id", "result_id", "number"],
    )
    op.create_index(
        "uq_research_revision_invocation_item",
        "research_result_revisions",
        ["origin_invocation_id", "output_item_key"],
        unique=True,
        postgresql_where=sa.text("origin_invocation_id IS NOT NULL"),
    )

    op.create_table(
        "research_citations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("research_revision_id", sa.UUID(), nullable=False),
        sa.Column("source_fragment_id", sa.UUID(), nullable=False),
        sa.Column("file_revision_id", sa.UUID(), nullable=False),
        sa.Column("claim_key", sa.String(length=120), nullable=False, server_default="root"),
        sa.Column("locator_override", postgresql.JSONB(), nullable=True),
        sa.Column("quoted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "research_revision_id", "claim_key", "source_fragment_id",
            name="uq_research_citation_claim",
        ),
        sa.ForeignKeyConstraint(
            ["research_revision_id", "project_id"],
            ["research_result_revisions.id", "research_result_revisions.project_id"],
            ondelete="RESTRICT", name="fk_research_citation_revision",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["source_fragment_id", "file_revision_id", "project_id"],
            [
                "source_fragments.id",
                "source_fragments.file_revision_id",
                "source_fragments.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_citation_fragment",
            deferrable=True, initially="DEFERRED",
        ),
        sa.CheckConstraint("claim_key <> ''", name="ck_research_citation_claim_key"),
    )
    op.create_index(
        "ix_research_citation_fragment",
        "research_citations",
        ["project_id", "file_revision_id", "research_revision_id"],
    )

    # The result -> current revision pointer can only be created after both tables.
    op.create_foreign_key(
        "fk_research_result_current_revision",
        "research_results",
        "research_result_revisions",
        ["current_revision_id", "id", "project_id"],
        ["id", "result_id", "project_id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )

    op.execute(
        """
        CREATE FUNCTION app.research_result_current_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          target research_result_revisions%ROWTYPE;
        BEGIN
          IF NEW.current_revision_id IS NOT DISTINCT FROM OLD.current_revision_id THEN
            IF NEW.version < OLD.version THEN
              RAISE EXCEPTION 'RESEARCH_RESULT_VERSION_REGRESSION';
            END IF;
            IF NEW.version > OLD.version + 1 THEN
              RAISE EXCEPTION 'RESEARCH_RESULT_VERSION_SKIP';
            END IF;
            RETURN NEW;
          END IF;
          SELECT * INTO target FROM research_result_revisions
           WHERE id = NEW.current_revision_id
             AND result_id = NEW.id
             AND project_id = NEW.project_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'RESEARCH_CURRENT_UNKNOWN_REVISION';
          END IF;
          IF target.applied_result_version IS NULL THEN
            RAISE EXCEPTION 'RESEARCH_CURRENT_UNAPPLIED_REVISION';
          END IF;
          IF target.applied_result_version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'RESEARCH_CURRENT_VERSION_MISMATCH';
          END IF;
          IF target.base_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
            RAISE EXCEPTION 'RESEARCH_CURRENT_BASE_MISMATCH';
          END IF;
          NEW.version := OLD.version + 1;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER research_result_current_guard BEFORE UPDATE ON research_results "
        "FOR EACH ROW EXECUTE FUNCTION app.research_result_current_guard()"
    )

    for table in ("research_results", "research_result_revisions", "research_citations"):
        _rls(table)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON research_results TO dramaforge_app"
    )
    op.execute("REVOKE DELETE, TRUNCATE ON research_results FROM dramaforge_app")
    _append_only("research_result_revisions")
    _append_only("research_citations")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS research_result_current_guard ON research_results")
    op.execute("DROP FUNCTION IF EXISTS app.research_result_current_guard()")
    for table in ("research_citations", "research_result_revisions", "research_results"):
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_constraint(
        "fk_research_result_current_revision", "research_results", type_="foreignkey",
    )
    op.drop_table("research_citations")
    op.drop_table("research_result_revisions")
    op.drop_table("research_results")
    op.drop_constraint("uq_director_invocation_scope", "director_invocations", type_="unique")
