"""Canonical Director Assistant persistence models.

The Assistant is proposal-only.  It owns conversation context and typed
proposals, but it never owns workflow, budget, batch, or media-execution
state.  Keeping these rows in a dedicated module makes that boundary visible
to model registration and prevents the retired controlled-Director models
from being imported accidentally.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import HASH_64, JSON_DOCUMENT


class DirectorThread(Base):
    """One Assistant conversation scoped to a project, scene, or shot."""

    __tablename__ = "director_threads"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_director_thread_project"),
        UniqueConstraint(
            "project_id",
            "scope_type",
            "scope_entity_id",
            name="uq_director_thread_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Director")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DirectorMessage(Base):
    """One Assistant message; messages contain no execution instructions."""

    __tablename__ = "director_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "project_id"], ["director_turns.id", "director_turns.project_id"],
            ondelete="CASCADE", name="fk_director_message_turn_scope",
        ),
        UniqueConstraint("turn_id", "ordinal", name="uq_director_message_turn_ordinal"),
        CheckConstraint("ordinal IS NULL OR ordinal >= 0", name="ck_director_message_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_threads.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[UUID | None] = mapped_column(nullable=True)
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index("ix_director_messages_thread", DirectorMessage.__table__.c.thread_id)


__all__ = ["DirectorMessage", "DirectorThread"]


class DirectorToolCall(Base):
    """One bounded tool call and result belonging to the same project as its Turn."""

    __tablename__ = "director_tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "project_id"], ["director_turns.id", "director_turns.project_id"],
            ondelete="CASCADE", name="fk_director_tool_call_turn_scope",
        ),
        UniqueConstraint("turn_id", "call_id", name="uq_director_tool_call_id"),
        CheckConstraint("step >= 0", name="ck_director_tool_call_step"),
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled','unknown_submission')",
            name="ck_director_tool_call_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    turn_id: Mapped[UUID] = mapped_column(nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    args_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    arguments: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index(
    "ix_director_tool_calls_turn_step",
    DirectorToolCall.__table__.c.turn_id,
    DirectorToolCall.__table__.c.step,
)
