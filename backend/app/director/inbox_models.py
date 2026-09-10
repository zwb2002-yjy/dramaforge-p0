"""Director-owned receipt and durable wakeup; production never writes these."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base


class DirectorInbox(Base):
    __tablename__ = "director_inbox"
    __table_args__ = (UniqueConstraint("consumer_id", "event_id", name="uq_director_inbox_event"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    consumer_id: Mapped[str] = mapped_column(String(100))
    event_id: Mapped[UUID] = mapped_column(ForeignKey("event_log.event_id", ondelete="RESTRICT"))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DirectorWakeup(Base):
    __tablename__ = "director_wakeups"
    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5", name="ck_director_wakeup_attempts"
        ),
    )

    inbox_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_inbox.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    dead_letter_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
