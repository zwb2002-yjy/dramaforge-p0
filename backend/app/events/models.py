"""Event log and transactional outbox models (fields mirror `04`)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import JSON_DOCUMENT
from app.shared.enums import OutboxStatus
from app.shared.pg_enums import OUTBOX_STATUS, col_enum


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(nullable=False, unique=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(nullable=False, unique=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        col_enum(OUTBOX_STATUS), nullable=False, default=OutboxStatus.PENDING.value
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    leased_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxDeadLetter(Base):
    __tablename__ = "outbox_dead_letters"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    outbox_event_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    event_id: Mapped[UUID] = mapped_column(nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error_summary: Mapped[str] = mapped_column(Text, nullable=False)
    dead_lettered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index(
    "idx_event_log_project_occurred",
    EventLog.__table__.c.project_id,
    EventLog.__table__.c.occurred_at,
)
