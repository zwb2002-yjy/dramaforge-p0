"""Independent cultural knowledge, project references and search projections (I4-03).

Four tables: an owner-scoped knowledge entry, its immutable revisions, private source
links readable only through the originating project, and project fixed references to
published revisions. Search text is a trigger-maintained deterministic projection of
the revision content (the portable test database cannot compile a PostgreSQL generated
column), with pg_trgm GIN indexes on PostgreSQL only.

Revision ID: 20261118_0113
Revises: 20261118_0112
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261118_0113"
down_revision: str | None = "20261118_0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _project_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
        "USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )


def _owner_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner_scope ON {table} FOR ALL "
        "USING (owner_user_id = app.current_user_id()) "
        "WITH CHECK (owner_user_id = app.current_user_id())"
    )


def _search_functions() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE FUNCTION app.research_search_text_v1(body jsonb) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$
          SELECT lower(regexp_replace(concat_ws(' ',
            body->>'text', body->>'coverage_note',
            body->>'display_name', body->>'description',
            body->>'theme', body->>'interpretation', body->>'related_material',
            body->'time'->>'label',
            (SELECT string_agg(value, ' ') FROM jsonb_array_elements_text(
               CASE WHEN jsonb_typeof(body->'aliases') = 'array'
                    THEN body->'aliases' ELSE '[]'::jsonb END)),
            (SELECT string_agg(
                concat_ws(' ', item->>'label', item->>'description', item->'time'->>'label'),
                ' ')
               FROM jsonb_array_elements(
                 CASE WHEN jsonb_typeof(body->'items') = 'array'
                      THEN body->'items' ELSE '[]'::jsonb END) AS item)
          ), '\\s+', ' ', 'g'))
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.knowledge_search_text_v1(title text, body jsonb) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$
          SELECT lower(regexp_replace(concat_ws(' ', title,
            body->>'text', body->>'summary',
            body->>'display_name', body->>'description',
            body->>'theme', body->>'interpretation', body->>'related_material',
            body->'time'->>'label',
            (SELECT string_agg(concat_ws(' ', item->>'heading', item->>'text'), ' ')
               FROM jsonb_array_elements(
                 CASE WHEN jsonb_typeof(body->'sections') = 'array'
                      THEN body->'sections' ELSE '[]'::jsonb END) AS item),
            (SELECT string_agg(value, ' ') FROM jsonb_array_elements_text(
               CASE WHEN jsonb_typeof(body->'aliases') = 'array'
                    THEN body->'aliases' ELSE '[]'::jsonb END))
          ), '\\s+', ' ', 'g'))
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.research_revision_search_text() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          NEW.search_text := app.research_search_text_v1(NEW.body);
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.knowledge_revision_search_text() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          NEW.search_text := app.knowledge_search_text_v1(NEW.title, NEW.body);
          RETURN NEW;
        END $$;
        """
    )


def _knowledge_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION app.knowledge_entry_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          target knowledge_revisions%ROWTYPE;
        BEGIN
          IF NEW.current_revision_id IS NOT DISTINCT FROM OLD.current_revision_id THEN
            IF NEW.version <> OLD.version THEN
              RAISE EXCEPTION 'KNOWLEDGE_VERSION_WITHOUT_DECISION';
            END IF;
            IF NEW.publication_status IS DISTINCT FROM OLD.publication_status THEN
              RAISE EXCEPTION 'KNOWLEDGE_STATUS_WITHOUT_DECISION';
            END IF;
            RETURN NEW;
          END IF;
          SELECT * INTO target FROM knowledge_revisions
           WHERE id = NEW.current_revision_id
             AND entry_id = NEW.id
             AND owner_user_id = NEW.owner_user_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'KNOWLEDGE_CURRENT_UNKNOWN_REVISION';
          END IF;
          IF NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'KNOWLEDGE_CURRENT_VERSION_MISMATCH';
          END IF;
          IF target.expected_entry_version <> OLD.version
             OR target.result_entry_version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'KNOWLEDGE_CURRENT_RESULT_MISMATCH';
          END IF;
          IF NEW.publication_status <> target.publication_status THEN
            RAISE EXCEPTION 'KNOWLEDGE_CURRENT_STATUS_MISMATCH';
          END IF;
          IF (NEW.publication_status = 'withdrawn') <> (NEW.withdrawn_at IS NOT NULL) THEN
            RAISE EXCEPTION 'KNOWLEDGE_WITHDRAWN_TIME_MISMATCH';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER knowledge_entry_guard BEFORE UPDATE ON knowledge_entries "
        "FOR EACH ROW EXECUTE FUNCTION app.knowledge_entry_guard()"
    )


def upgrade() -> None:
    _search_functions()

    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("current_revision_id", sa.UUID(), nullable=True),
        sa.Column("publication_status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_entry_workspace",
        ),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_knowledge_entry_owner"),
        sa.CheckConstraint(
            "kind IN ('summary','person','place','event','timeline','cultural_clue')",
            name="ck_knowledge_entry_kind",
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','published','withdrawn')",
            name="ck_knowledge_entry_status",
        ),
        sa.CheckConstraint(
            "(publication_status = 'withdrawn') = (withdrawn_at IS NOT NULL)",
            name="ck_knowledge_entry_withdrawn",
        ),
        sa.CheckConstraint("version > 0", name="ck_knowledge_entry_version"),
    )
    op.create_index(
        "ix_knowledge_entry_owner",
        "knowledge_entries",
        ["owner_user_id", "publication_status", "kind", "id"],
    )

    op.create_table(
        "knowledge_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("allowed_uses", postgresql.JSONB(), nullable=False),
        sa.Column("public_source_notes", postgresql.JSONB(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("publication_status", sa.String(length=16), nullable=False),
        sa.Column("expected_entry_version", sa.Integer(), nullable=False),
        sa.Column("result_entry_version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "owner_user_id"],
            ["knowledge_entries.id", "knowledge_entries.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_revision_entry",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint("entry_id", "number", name="uq_knowledge_revision_number"),
        sa.UniqueConstraint("owner_user_id", "request_key", name="uq_knowledge_revision_request"),
        sa.UniqueConstraint(
            "id", "entry_id", "owner_user_id", name="uq_knowledge_revision_scope",
        ),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_knowledge_revision_owner"),
        sa.UniqueConstraint(
            "entry_id", "result_entry_version", name="uq_knowledge_revision_result",
        ),
        sa.CheckConstraint("number > 0", name="ck_knowledge_revision_number"),
        sa.CheckConstraint("expected_entry_version > 0", name="ck_knowledge_expected_version"),
        sa.CheckConstraint("result_entry_version > 1", name="ck_knowledge_result_version"),
        sa.CheckConstraint(
            "result_entry_version = expected_entry_version + 1",
            name="ck_knowledge_result_increment",
        ),
        sa.CheckConstraint(
            "operation IN ('save_draft','publish','withdraw')",
            name="ck_knowledge_revision_operation",
        ),
        sa.CheckConstraint(
            "publication_status IN ('draft','published','withdrawn')",
            name="ck_knowledge_revision_status",
        ),
        sa.CheckConstraint(
            "(operation = 'save_draft' AND publication_status = 'draft') "
            "OR (operation = 'publish' AND publication_status = 'published') "
            "OR (operation = 'withdraw' AND publication_status = 'withdrawn')",
            name="ck_knowledge_operation_status",
        ),
    )
    op.create_index(
        "ix_knowledge_revision_entry",
        "knowledge_revisions",
        ["owner_user_id", "entry_id", "number"],
    )

    op.create_table(
        "knowledge_source_links",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("research_revision_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_revision_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_project",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["research_revision_id", "project_id"],
            ["research_result_revisions.id", "research_result_revisions.project_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_research",
            deferrable=True, initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_revision_id", "owner_user_id"],
            ["knowledge_revisions.id", "knowledge_revisions.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_revision",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "knowledge_revision_id", "research_revision_id", name="uq_knowledge_source_link",
        ),
    )

    op.create_table(
        "project_knowledge_references",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_entry_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_revision_id", sa.UUID(), nullable=False),
        sa.Column("allowed_use", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("detached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_project_knowledge_reference_project",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_project_knowledge_reference_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_revision_id", "knowledge_entry_id", "owner_user_id"],
            [
                "knowledge_revisions.id",
                "knowledge_revisions.entry_id",
                "knowledge_revisions.owner_user_id",
            ],
            ondelete="RESTRICT", name="fk_project_knowledge_reference_revision",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "project_id", "knowledge_revision_id", "allowed_use",
            name="uq_project_knowledge_reference",
        ),
        sa.CheckConstraint("version > 0", name="ck_project_knowledge_reference_version"),
    )
    op.create_index(
        "ix_project_knowledge_reference_project",
        "project_knowledge_references",
        ["project_id", "detached_at", "id"],
    )

    op.create_foreign_key(
        "fk_knowledge_entry_current_revision",
        "knowledge_entries",
        "knowledge_revisions",
        ["current_revision_id", "id", "owner_user_id"],
        ["id", "entry_id", "owner_user_id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )
    _knowledge_guard()

    op.add_column(
        "research_result_revisions", sa.Column("search_text", sa.Text(), nullable=False,
                                                server_default=""),
    )
    op.execute(
        "CREATE TRIGGER research_revision_search_text BEFORE INSERT ON "
        "research_result_revisions FOR EACH ROW EXECUTE FUNCTION "
        "app.research_revision_search_text()"
    )
    op.execute(
        "CREATE TRIGGER knowledge_revision_search_text BEFORE INSERT ON "
        "knowledge_revisions FOR EACH ROW EXECUTE FUNCTION "
        "app.knowledge_revision_search_text()"
    )
    op.execute(
        "CREATE INDEX ix_research_revision_search ON research_result_revisions "
        "USING gin (search_text gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_revision_search ON knowledge_revisions "
        "USING gin (search_text gin_trgm_ops)"
    )

    _owner_rls("knowledge_entries")
    _owner_rls("knowledge_revisions")
    _project_rls("knowledge_source_links")
    _project_rls("project_knowledge_references")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON knowledge_entries TO dramaforge_app"
    )
    op.execute("REVOKE DELETE, TRUNCATE ON knowledge_entries FROM dramaforge_app")
    for table in ("knowledge_revisions", "knowledge_source_links"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO dramaforge_app")
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM dramaforge_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON project_knowledge_references TO dramaforge_app"
    )
    op.execute("REVOKE DELETE, TRUNCATE ON project_knowledge_references FROM dramaforge_app")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_revision_search")
    op.execute("DROP INDEX IF EXISTS ix_research_revision_search")
    op.execute(
        "DROP TRIGGER IF EXISTS knowledge_revision_search_text ON knowledge_revisions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS research_revision_search_text ON research_result_revisions"
    )
    op.drop_column("research_result_revisions", "search_text")
    op.execute("DROP TRIGGER IF EXISTS knowledge_entry_guard ON knowledge_entries")
    op.execute("DROP FUNCTION IF EXISTS app.knowledge_entry_guard()")
    op.drop_constraint(
        "fk_knowledge_entry_current_revision", "knowledge_entries", type_="foreignkey",
    )
    for table in (
        "project_knowledge_references",
        "knowledge_source_links",
        "knowledge_revisions",
        "knowledge_entries",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_scope ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_table("project_knowledge_references")
    op.drop_table("knowledge_source_links")
    op.drop_table("knowledge_revisions")
    op.drop_table("knowledge_entries")
    op.execute("DROP FUNCTION IF EXISTS app.knowledge_revision_search_text()")
    op.execute("DROP FUNCTION IF EXISTS app.research_revision_search_text()")
    op.execute("DROP FUNCTION IF EXISTS app.knowledge_search_text_v1(text, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS app.research_search_text_v1(jsonb)")
