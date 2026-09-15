"""Durable identities and verified results for individual director text calls."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import JSON_DOCUMENT


class DirectorInvocation(Base):
    __tablename__ = "director_invocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "project_id"], ["director_turns.id", "director_turns.project_id"],
            ondelete="CASCADE", name="fk_director_invocation_turn_scope",
        ),
        UniqueConstraint("turn_id", "invocation_key", name="uq_director_invocation_key"),
        CheckConstraint("attempt > 0", name="ck_director_invocation_attempt"),
        CheckConstraint(
            "status IN ('prepared','submission_started','completed','failed','unknown_submission')",
            name="ck_director_invocation_status",
        ),
        CheckConstraint(
            "(status = 'completed' AND output_hash IS NOT NULL AND validated_output IS NOT NULL) "
            "OR (status <> 'completed' AND output_hash IS NULL AND validated_output IS NULL)",
            name="ck_director_invocation_output",
        ),
        CheckConstraint(
            "(cost_status = 'unknown' AND reported_cost IS NULL) OR "
            "(cost_status = 'reported' AND reported_cost IS NOT NULL AND reported_cost >= 0)",
            name="ck_director_invocation_cost",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    turn_id: Mapped[UUID] = mapped_column(nullable=False)
    invocation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    step_key: Mapped[str] = mapped_column(String(160), nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_resolution: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    request_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    intent_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared")
    validated_output: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True,
    )
    output_hash: Mapped[str | None] = mapped_column(String(64))
    token_usage: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict,
    )
    reported_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    cost_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    error_code: Mapped[str | None] = mapped_column(String(120))
    response_summary: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submission_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
