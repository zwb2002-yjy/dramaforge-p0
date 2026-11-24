"""Immutable source extraction snapshots and the forward-only current pointer.

Existing ``native-text-v1`` excerpts (one-based locations) are converted to
schema-2 fragments (zero-based, half-open ranges) with the original location kept
as evidence. A location this conversion cannot account for blocks the migration
with a safe id list instead of dropping evidence or inventing coordinates. The
legacy inline column is removed in the same step: one extraction implementation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20261117_0101"
down_revision = "20261117_0100"
branch_labels = None
depends_on = None

CONVERSION = "native-text-v1-to-schema2"
PARSER_KEY = "legacy-native-text-v1"


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _paragraph(text: str, index: int, **extra: object) -> tuple[str, dict[str, object]]:
    return "paragraph", {
        "kind": "paragraph",
        **extra,
        "paragraph_start": index,
        "paragraph_end": index + 1,
        "char_start": 0,
        "char_end": len(text),
    }


def _table_cell(
    row: int, column: int, **extra: object,
) -> tuple[str, dict[str, object]]:
    return "table_cells", {
        "kind": "table_cells",
        **extra,
        "row_start": row - 1,
        "row_end": row,
        "column_start": column - 1,
        "column_end": column,
    }


def _convert(text: str, location: object) -> tuple[str, dict[str, object], dict[str, object]]:
    """Map one legacy one-based location to schema 2 plus its original evidence."""
    if not isinstance(location, Mapping):
        raise ValueError("location_not_object")
    keys = set(location)
    if keys == {"line"}:
        line = location["line"]
        if not isinstance(line, int) or line < 1:
            raise ValueError("location_line_invalid")
        # The native text parser splits lines and drops only the terminator, so
        # line n owns the whole fragment text; the source line is still n-1..n.
        kind, locator = _paragraph(text, line - 1, container_key="text-lines")
    elif keys == {"row", "column", "line_start", "line_end"}:
        row, column = location["row"], location["column"]
        if not isinstance(row, int) or not isinstance(column, int) or row < 1 or column < 1:
            raise ValueError("location_table_invalid")
        kind, locator = _table_cell(row, column, sheet="data")
    elif keys == {"part", "paragraph"}:
        paragraph = location["paragraph"]
        part = location["part"]
        if not isinstance(part, str) or not part or not isinstance(paragraph, int) or paragraph < 1:
            raise ValueError("location_docx_paragraph_invalid")
        kind, locator = _paragraph(
            text, paragraph - 1, part_path=part, container_key="body",
        )
    elif keys == {"part", "table", "row", "column", "paragraph"}:
        table, row, column, paragraph = (
            location["table"], location["row"], location["column"], location["paragraph"],
        )
        if (
            not isinstance(table, int) or table < 1
            or not isinstance(row, int) or row < 1
            or not isinstance(column, int) or column < 1
            or not isinstance(paragraph, int) or paragraph < 1
        ):
            raise ValueError("location_docx_table_invalid")
        kind, locator = _table_cell(
            row, column,
            part_path=location["part"],
            container_key=f"table:{table - 1}",
            cell_paragraph=paragraph - 1,
        )
    else:
        raise ValueError("location_shape_unknown")
    evidence = {
        "original_location": dict(location),
        "conversion": CONVERSION,
    }
    return kind, locator, evidence


def _processor_evidence() -> dict[str, object]:
    settings = json.dumps(
        {"conversion": CONVERSION, "index_base": 0}, sort_keys=True, separators=(",", ":"),
    )
    return {
        "schema_version": 1,
        "processors": [{
            "ref": PARSER_KEY,
            "engine": "alembic-data-conversion",
            "version": CONVERSION,
            "settings_hash": _hash(settings),
            "network_mode": "local",
        }],
        "coordinate_system": {"index_base": 0, "bbox_origin": "top_left"},
    }


def _backfill(connection: sa.engine.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT id, project_id, file_id, number, attempt, parser_version, excerpts, created_at "
            "FROM project_file_revisions WHERE status = 'parsed' ORDER BY created_at, id"
        )
    ).mappings().all()
    blocked: list[str] = []
    for row in rows:
        excerpts = row["excerpts"] or []
        if not isinstance(excerpts, Sequence) or isinstance(excerpts, (str, bytes)):
            blocked.append(str(row["id"]))
            continue
        fragments: list[tuple[int, str, dict[str, object], str, dict[str, object]]] = []
        try:
            for ordinal, excerpt in enumerate(excerpts):
                if not isinstance(excerpt, Mapping):
                    raise ValueError("excerpt_not_object")
                text = excerpt.get("text")
                if not isinstance(text, str):
                    raise ValueError("excerpt_text_invalid")
                kind, locator, evidence = _convert(text, excerpt.get("location"))
                fragments.append((ordinal, kind, locator, text, evidence))
        except ValueError:
            blocked.append(str(row["id"]))
            continue
        if not fragments:
            blocked.append(str(row["id"]))
            continue
        content_hash = _hash([
            [ordinal, kind, locator, text] for ordinal, kind, locator, text, _ in fragments
        ])
        coverage = {
            "schema_version": 1,
            "units_total": len(fragments),
            "units_processed": len(fragments),
            "omitted_units": 0,
            "omitted_reasons": [],
            "complete": True,
        }
        extraction_id = connection.execute(
            sa.text(
                "INSERT INTO source_extractions (id, project_id, file_id, file_revision_id, "
                "attempt, parser_key, parser_version, content_hash, extraction_schema_version, "
                "coverage, processor_evidence, completed_at) VALUES "
                "(gen_random_uuid(), :project_id, :file_id, :revision_id, :attempt, :parser_key, "
                ":parser_version, :content_hash, 2, :coverage, :processor_evidence, :completed_at) "
                "RETURNING id"
            ),
            {
                "project_id": row["project_id"],
                "file_id": row["file_id"],
                "revision_id": row["id"],
                "attempt": row["attempt"],
                "parser_key": PARSER_KEY,
                "parser_version": row["parser_version"] or PARSER_KEY,
                "content_hash": content_hash,
                "coverage": json.dumps(coverage),
                "processor_evidence": json.dumps(_processor_evidence()),
                "completed_at": row["created_at"],
            },
        ).scalar_one()
        for ordinal, kind, locator, text, evidence in fragments:
            connection.execute(
                sa.text(
                    "INSERT INTO source_fragments (id, project_id, extraction_id, "
                    "file_revision_id, ordinal, locator_kind, locator, text_content, "
                    "content_hash, extraction_method, processor_ref, evidence_meta) VALUES "
                    "(gen_random_uuid(), :project_id, :extraction_id, :revision_id, :ordinal, "
                    ":locator_kind, :locator, :text_content, :content_hash, 'native_text', "
                    ":processor_ref, :evidence_meta)"
                ),
                {
                    "project_id": row["project_id"],
                    "extraction_id": extraction_id,
                    "revision_id": row["id"],
                    "ordinal": ordinal,
                    "locator_kind": kind,
                    "locator": json.dumps(locator),
                    "text_content": text,
                    "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                    "processor_ref": PARSER_KEY,
                    "evidence_meta": json.dumps(evidence),
                },
            )
        connection.execute(
            sa.text(
                "UPDATE project_file_revisions SET current_extraction_id = :extraction_id "
                "WHERE id = :revision_id"
            ),
            {"extraction_id": extraction_id, "revision_id": row["id"]},
        )
    if blocked:
        raise RuntimeError(
            "SOURCE_LEGACY_LOCATION_UNSUPPORTED:" + ",".join(sorted(blocked))
        )
    unparsed = connection.execute(
        sa.text(
            "SELECT id FROM project_file_revisions WHERE status = 'parsed' AND "
            "current_extraction_id IS NULL LIMIT 20"
        )
    ).scalars().all()
    if unparsed:
        raise RuntimeError("SOURCE_LEGACY_EXTRACTION_MISSING:" + ",".join(map(str, unparsed)))


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("SOURCE_EXTRACTION_MIGRATION_REQUIRES_ONLINE_BACKFILL")
    op.create_unique_constraint(
        "uq_project_file_revision_scope", "project_file_revisions", ["id", "file_id", "project_id"],
    )
    op.add_column(
        "project_file_revisions", sa.Column("current_extraction_id", sa.UUID(), nullable=True),
    )
    op.create_table(
        "source_extractions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("file_revision_id", sa.UUID(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("parser_key", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("extraction_schema_version", sa.Integer(), nullable=False),
        sa.Column("coverage", postgresql.JSONB(), nullable=False),
        sa.Column("processor_evidence", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["file_revision_id", "file_id", "project_id"],
            ["project_file_revisions.id", "project_file_revisions.file_id",
             "project_file_revisions.project_id"],
            name="fk_source_extraction_revision_scope", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("file_revision_id", "attempt", name="uq_source_extraction_attempt"),
        sa.UniqueConstraint(
            "id", "file_revision_id", "project_id", name="uq_source_extraction_scope",
        ),
        sa.CheckConstraint("attempt > 0", name="ck_source_extraction_attempt"),
        sa.CheckConstraint(
            "extraction_schema_version > 0", name="ck_source_extraction_schema_version",
        ),
    )
    op.create_index(
        "ix_source_extraction_revision", "source_extractions",
        ["project_id", "file_revision_id", "created_at", "id"],
    )
    op.create_table(
        "source_fragments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("extraction_id", sa.UUID(), nullable=False),
        sa.Column("file_revision_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator_kind", sa.String(24), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("extraction_method", sa.String(24), nullable=False),
        sa.Column("processor_ref", sa.String(80), nullable=False),
        sa.Column("evidence_meta", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["extraction_id", "file_revision_id", "project_id"],
            ["source_extractions.id", "source_extractions.file_revision_id",
             "source_extractions.project_id"],
            name="fk_source_fragment_extraction_scope", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("extraction_id", "ordinal", name="uq_source_fragment_ordinal"),
        sa.UniqueConstraint(
            "id", "file_revision_id", "project_id", name="uq_source_fragment_scope",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_source_fragment_ordinal"),
        sa.CheckConstraint(
            "locator_kind IN ('paragraph','page_region','image_region','time_range',"
            "'table_cells')",
            name="ck_source_fragment_locator_kind",
        ),
        sa.CheckConstraint(
            "extraction_method IN ('native_text','ocr','transcript','visual_input','metadata')",
            name="ck_source_fragment_extraction_method",
        ),
    )
    op.create_index(
        "ix_source_fragment_revision", "source_fragments",
        ["project_id", "file_revision_id", "ordinal"],
    )
    # Backfill while the legacy column still exists, then drop it. The pointer FK
    # is added last: PostgreSQL refuses to ALTER a table that already queued
    # deferred constraint checks, so the constraint must arrive after the updates.
    _backfill(op.get_bind())
    op.drop_column("project_file_revisions", "excerpts")
    op.create_foreign_key(
        "fk_project_file_revision_current_extraction",
        "project_file_revisions", "source_extractions",
        ["current_extraction_id", "id", "project_id"],
        ["id", "file_revision_id", "project_id"],
        ondelete="NO ACTION", deferrable=True, initially="DEFERRED",
    )
    for table in ("source_extractions", "source_fragments"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
            "USING (project_id = app.current_project_id()) "
            "WITH CHECK (project_id = app.current_project_id())"
        )
        # Extraction snapshots are append-only. The schema-wide default
        # privileges grant the runtime role every verb on new tables, so the
        # write verbs must be revoked explicitly rather than merely not granted.
        op.execute(f"GRANT SELECT, INSERT ON {table} TO dramaforge_app")
        op.execute(
            f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM dramaforge_app"
        )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("SOURCE_EXTRACTION_DOWNGRADE_REQUIRES_ONLINE_PREFLIGHT")
    connection = op.get_bind()
    populated = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM source_extractions) OR EXISTS(SELECT 1 FROM source_fragments)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("SOURCE_EXTRACTIONS_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE")
    for table in ("source_extractions", "source_fragments"):
        op.execute(f"DROP POLICY {table}_project_scope ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_constraint(
        "fk_project_file_revision_current_extraction", "project_file_revisions", type_="foreignkey",
    )
    op.add_column(
        "project_file_revisions",
        sa.Column("excerpts", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
    )
    op.drop_index("ix_source_fragment_revision", table_name="source_fragments")
    op.drop_table("source_fragments")
    op.drop_index("ix_source_extraction_revision", table_name="source_extractions")
    op.drop_table("source_extractions")
    op.drop_column("project_file_revisions", "current_extraction_id")
    op.drop_constraint(
        "uq_project_file_revision_scope", "project_file_revisions", type_="unique",
    )
