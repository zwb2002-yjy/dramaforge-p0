"""PostgreSQL enum column helpers (Alembic owns CREATE TYPE)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Enum, String
from sqlalchemy.types import TypeEngine

from app.shared.enums import GraphStatus, OutboxStatus, ProjectStage


def pg_str_enum(name: str, *values: str) -> Enum:
    return Enum(
        *values,
        name=name,
        create_constraint=False,
        native_enum=True,
        validate_strings=True,
    )


def pg_py_enum(enum_cls: type, name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        create_constraint=False,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def col_enum(pg: Enum, sqlite_len: int = 32) -> TypeEngine[Any]:
    return pg.with_variant(String(sqlite_len), "sqlite")


PROJECT_STAGE = pg_py_enum(ProjectStage, "project_stage")
OUTBOX_STATUS = pg_py_enum(OutboxStatus, "outbox_status")
GRAPH_STATUS = pg_py_enum(GraphStatus, "graph_status")
