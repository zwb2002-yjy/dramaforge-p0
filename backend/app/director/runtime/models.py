"""Engine binding, lease fencing and durable resume claims for Director runtime."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import JSON_DOCUMENT


class DirectorRuntimeControl(Base):
    __tablename__ = "director_runtime_controls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "project_id"],
            ["director_turns.id", "director_turns.project_id"],
            ondelete="CASCADE",
            name="fk_director_runtime_control_turn_scope",
        ),
        UniqueConstraint("turn_id", name="uq_director_runtime_control_turn"),
        UniqueConstraint(
            "runtime_execution_id", "project_id",
            name="uq_director_runtime_control_execution_scope",
        ),
        CheckConstraint("revision > 0", name="ck_director_runtime_control_revision"),
        CheckConstraint("lease_epoch >= 0", name="ck_director_runtime_control_epoch"),
        CheckConstraint(
            "status IN ('active','waiting','stopped','completed','failed','stale')",
            name="ck_director_runtime_control_status",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_director_runtime_control_lease",
        ),
    )

    runtime_execution_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    turn_id: Mapped[UUID] = mapped_column(nullable=False)
    engine_version: Mapped[str] = mapped_column(String(120), nullable=False)
    state_schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class DirectorRuntimeSignalClaim(Base):
    __tablename__ = "director_runtime_signal_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["runtime_execution_id", "project_id"],
            [
                "director_runtime_controls.runtime_execution_id",
                "director_runtime_controls.project_id",
            ],
            ondelete="CASCADE",
            name="fk_director_runtime_signal_execution_scope",
        ),
        CheckConstraint("expected_revision > 0", name="ck_director_runtime_signal_revision"),
        CheckConstraint("lease_epoch > 0", name="ck_director_runtime_signal_epoch"),
    )

    signal_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    runtime_execution_id: Mapped[UUID] = mapped_column(primary_key=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class DirectorRuntimeWakeup(Base):
    __tablename__ = "director_runtime_wakeups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["runtime_execution_id", "project_id"],
            [
                "director_runtime_controls.runtime_execution_id",
                "director_runtime_controls.project_id",
            ],
            ondelete="CASCADE",
            name="fk_director_runtime_wakeup_execution_scope",
        ),
        UniqueConstraint(
            "project_id", "dedupe_key", name="uq_director_runtime_wakeup_dedupe",
        ),
        CheckConstraint(
            "kind IN ('start','resume','stop','recovery')",
            name="ck_director_runtime_wakeup_kind",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5",
            name="ck_director_runtime_wakeup_attempts",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    runtime_execution_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_letter_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


Index(
    "ix_director_runtime_wakeups_pending",
    DirectorRuntimeWakeup.__table__.c.next_attempt_at,
    DirectorRuntimeWakeup.__table__.c.id,
    postgresql_where=(
        DirectorRuntimeWakeup.__table__.c.completed_at.is_(None)
        & DirectorRuntimeWakeup.__table__.c.dead_letter_at.is_(None)
    ),
)


__all__ = [
    "DirectorRuntimeControl",
    "DirectorRuntimeSignalClaim",
    "DirectorRuntimeWakeup",
]
