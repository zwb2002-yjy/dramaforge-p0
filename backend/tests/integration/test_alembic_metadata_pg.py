"""Full PostgreSQL migration-head versus ORM metadata drift proof."""

from __future__ import annotations

import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from pg_support import alembic_head, available, database_url
from sqlalchemy import CheckConstraint, create_engine, text

_DATABASE_URL = database_url("postgresql+psycopg")
# Project-named CHECK constraints carry the `ck_` prefix. Comparing all of
# them (instead of a hand-maintained subset) auto-discovers every new check and
# fails when either side is missing one.
_CHECK_NAME_PREFIX = "ck_"
pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not available(_DATABASE_URL),
    reason="set TEST_PG_ENABLED=1 with an available PostgreSQL quality database",
)


def _orm_checks(connection) -> dict[tuple[str, str], str]:
    """Use PostgreSQL's parser/deparser, never rewrite SQL semantics with regex.

    Empty temporary copies use the migrated column types (already checked by
    compare_metadata). Only ORM CHECKs are added; LIKE does not copy CHECKs.
    No application table/data or migration is changed by this round trip.
    """
    load_all_models()
    result: dict[tuple[str, str], str] = {}
    quote = connection.dialect.identifier_preparer.quote
    for table in Base.metadata.sorted_tables:
        checks = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
            and constraint.name is not None
            and constraint.name.startswith(_CHECK_NAME_PREFIX)
        ]
        if not checks:
            continue
        temporary = "_quality_orm_check_shadow"
        connection.exec_driver_sql(
            f"CREATE TEMP TABLE {quote(temporary)} (LIKE public.{quote(table.name)}) ON COMMIT DROP"
        )
        try:
            for constraint in checks:
                sql = str(
                    constraint.sqltext.compile(
                        dialect=connection.dialect, compile_kwargs={"literal_binds": True}
                    )
                )
                connection.exec_driver_sql(
                    f"ALTER TABLE pg_temp.{quote(temporary)} "
                    f"ADD CONSTRAINT {quote(constraint.name)} CHECK ({sql})"
                )
            rows = connection.execute(
                text(
                    "SELECT conname, pg_get_expr(conbin, conrelid) "
                    "FROM pg_constraint WHERE contype = 'c' "
                    "AND conrelid = to_regclass(:table)"
                ),
                {"table": f"pg_temp.{temporary}"},
            ).all()
            result.update({(table.name, name): expression for name, expression in rows})
        finally:
            connection.exec_driver_sql(f"DROP TABLE pg_temp.{quote(temporary)}")
    return result


def _database_checks(connection) -> dict[tuple[str, str], str]:
    rows = connection.execute(
        text(
            "SELECT t.relname, c.conname, pg_get_expr(c.conbin, c.conrelid) "
            "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'public' AND c.contype = 'c'"
        )
    ).all()
    return {
        (table, name): expression
        for table, name, expression in rows
        if name.startswith(_CHECK_NAME_PREFIX)
    }


def _database_enum_labels(connection) -> dict[str, tuple[str, ...]]:
    rows = connection.execute(
        text(
            "SELECT t.typname, e.enumlabel "
            "FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname = 'public' "
            "ORDER BY t.typname, e.enumsortorder"
        )
    ).all()
    labels: dict[str, list[str]] = {}
    for type_name, label in rows:
        labels.setdefault(type_name, []).append(label)
    return {name: tuple(values) for name, values in labels.items()}


def test_migration_head_has_no_orm_metadata_drift() -> None:
    """Compare every reflected table shape plus every project-named CHECK."""
    load_all_models()
    engine = create_engine(_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == alembic_head()

            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    # The project intentionally keeps most creation defaults
                    # in Python rather than duplicating them as server defaults.
                    "compare_server_default": False,
                },
            )
            diffs = compare_metadata(context, Base.metadata)
            assert diffs == [], f"Alembic metadata drift: {diffs!r}"

            orm_checks = _orm_checks(connection)
            database_checks = _database_checks(connection)
            assert database_checks.keys() == orm_checks.keys(), (
                "CHECK constraint drift: "
                f"missing={sorted(orm_checks.keys() - database_checks.keys())}, "
                f"extra={sorted(database_checks.keys() - orm_checks.keys())}"
            )
            assert database_checks == orm_checks, "CHECK constraint expressions drifted"

            enum_labels = _database_enum_labels(connection)
            assert "face_review" not in enum_labels["node_type"]
            orphan_enums = (
                connection.execute(
                    text(
                        "SELECT t.typname "
                        "FROM pg_type t "
                        "JOIN pg_namespace n ON n.oid = t.typnamespace "
                        "WHERE n.nspname = 'public' AND t.typtype = 'e' "
                        "AND NOT EXISTS ("
                        "SELECT 1 FROM pg_attribute a "
                        "JOIN pg_class c ON c.oid = a.attrelid "
                        "JOIN pg_namespace cn ON cn.oid = c.relnamespace "
                        "WHERE a.atttypid = t.oid AND a.attnum > 0 "
                        "AND NOT a.attisdropped AND cn.nspname = 'public'"
                        ") ORDER BY t.typname"
                    )
                )
                .scalars()
                .all()
            )
            assert orphan_enums == [], f"orphan public enum types: {orphan_enums!r}"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("table_name", "check_name", "changed_sql"),
    [
        ("users", "ck_users_version_positive", "version >= 0"),
        (
            "review_annotations",
            "ck_review_annotation_range",
            "time_end IS NULL AND (time_start IS NULL OR time_end >= time_start)",
        ),
        (
            "artifact_reference_tokens",
            "ck_artifact_reference_token_creator",
            "(created_by_run_id IS NOT NULL) = (created_by_user_id IS NOT NULL)",
        ),
    ],
)
def test_check_comparison_detects_semantic_changes(
    table_name: str,
    check_name: str,
    changed_sql: str,
) -> None:
    """Comparison still detects boundary, grouping and XOR changes."""
    load_all_models()
    constraint = next(
        item
        for item in Base.metadata.tables[table_name].constraints
        if isinstance(item, CheckConstraint) and item.name == check_name
    )
    original = constraint.sqltext
    engine = create_engine(_DATABASE_URL, pool_pre_ping=True)
    try:
        constraint.sqltext = text(changed_sql)
        with engine.connect() as connection:
            key = (table_name, check_name)
            assert _orm_checks(connection)[key] != _database_checks(connection)[key]
    finally:
        constraint.sqltext = original
        engine.dispose()
