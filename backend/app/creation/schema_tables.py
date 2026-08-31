"""Core tables whose schema is migration-owned but has no CRUD model.

``materialization_operations`` is persisted by the creation service and has
always existed in the PostgreSQL migration history.  Keeping its complete
definition in ``Base.metadata`` lets standalone Alembic comparisons see the
table without inventing a second declarative business model.
"""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql

from app.shared.base import Base

_materialization_operation_status = Enum(
    "pending",
    "completed",
    "failed",
    name="materialization_operation_status",
    create_constraint=False,
    native_enum=True,
    validate_strings=True,
)

materialization_operations = Table(
    "materialization_operations",
    Base.metadata,
    # The migration is authoritative for this table's UUID/default shape.
    # ``postgresql.UUID`` renders as UUID on PostgreSQL and remains usable by
    # the existing unit-test dialects without introducing CRUD behavior.
    Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
    Column("creation_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
    Column("operation_key", String(120), nullable=False),
    Column("operation_kind", String(80), nullable=False),
    Column("payload_hash", CHAR(64), nullable=False),
    Column(
        "status",
        _materialization_operation_status,
        server_default="pending",
        nullable=False,
    ),
    Column("result_entity_type", String(80), nullable=True),
    Column("result_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
    Column("error_code", String(100), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ["project_id"], ["projects.id"], ondelete="CASCADE"
    ),
    ForeignKeyConstraint(
        ["creation_plan_id"], ["creation_plans.id"], ondelete="CASCADE"
    ),
    UniqueConstraint("creation_plan_id", "operation_key"),
    CheckConstraint(
        "(status = 'completed') = (result_entity_type IS NOT NULL AND result_entity_id IS NOT NULL)"
    ),
)

Index(
    "idx_materialization_operations_project_plan",
    materialization_operations.c.project_id,
    materialization_operations.c.creation_plan_id,
    materialization_operations.c.status,
)

__all__ = ["materialization_operations"]
