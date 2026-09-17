"""Full PostgreSQL migration-head versus ORM metadata drift proof."""

from __future__ import annotations

import os
import re

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from pg_support import alembic_head, available, database_url
from sqlalchemy import CheckConstraint, create_engine, inspect, text

_DATABASE_URL = database_url("postgresql+psycopg")
_CANONICAL_CHECK_NAMES = {
    "ck_human_review_decision_value",
    "ck_repair_request_option",
    "ck_node_runs_cached_reused",
    "ck_node_runs_completed_artifact",
    "ck_node_runs_cached_zero_cost",
}
pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not available(_DATABASE_URL),
    reason="set TEST_PG_ENABLED=1 with an available PostgreSQL quality database",
)


def _normalize_check_sql(value: str) -> str:
    """Normalize formatting/casts while retaining the check expression shape."""
    normalized = value.lower()
    normalized = re.sub(
        r"::(?:character varying|[a-z_][a-z0-9_]*)(?:\[\])?", "", normalized
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*=\s*any\s*\(\s*array\s*\[([^]]*)\]\s*\)?",
        r"\1 in (\2)",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*<>\s*all\s*\(\s*array\s*\[([^]]*)\]\s*\)?",
        r"\1 not in (\2)",
        normalized,
    )
    normalized = normalized.replace("[]", "")
    normalized = re.sub(r"\s*([(),])\s*", r"\1", normalized)
    normalized = re.sub(r"\)(and|or)\b", r") \1", normalized)
    normalized = re.sub(
        r"\(([^()]*\s(?:<>|>=|<=|=)\s[^()]*)\)", r"\1", normalized
    )
    normalized = re.sub(r"\s*(and|or)\s*", r" \1 ", normalized)
    return " ".join(normalized.split())


def _orm_checks() -> dict[tuple[str, str], str]:
    load_all_models()
    return {
        (table.name, constraint.name): _normalize_check_sql(str(constraint.sqltext))
        for table in Base.metadata.sorted_tables
        for constraint in table.constraints
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name in _CANONICAL_CHECK_NAMES
        )
    }


def _database_checks(connection) -> dict[tuple[str, str], str]:
    inspector = inspect(connection)
    return {
        (table_name, item["name"]): _normalize_check_sql(item["sqltext"])
        for table_name in inspector.get_table_names(schema="public")
        for item in inspector.get_check_constraints(table_name, schema="public")
        if (
            item.get("name") in _CANONICAL_CHECK_NAMES
            and item.get("sqltext") is not None
        )
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
    """Compare every reflected table shape plus named CHECK constraints."""
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

            orm_checks = _orm_checks()
            database_checks = _database_checks(connection)
            assert database_checks.keys() == orm_checks.keys(), (
                "CHECK constraint drift: "
                f"missing={sorted(orm_checks.keys() - database_checks.keys())}, "
                f"extra={sorted(database_checks.keys() - orm_checks.keys())}"
            )
            assert database_checks == orm_checks, "CHECK constraint expressions drifted"

            enum_labels = _database_enum_labels(connection)
            assert "face_review" not in enum_labels["node_type"]
            orphan_enums = connection.execute(
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
            ).scalars().all()
            assert orphan_enums == [], f"orphan public enum types: {orphan_enums!r}"
    finally:
        engine.dispose()
