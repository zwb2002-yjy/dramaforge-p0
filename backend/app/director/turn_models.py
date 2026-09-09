"""Durable, bounded Director decision turns.

A DirectorTurn is the Director-layer record for one request and its text-model
evidence. It references canonical proposal/production facts but never replaces
NodeRun, ProviderOperation, Artifact, or the editable Scene/Shot truth.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import CURRENCY_CODE, HASH_64, JSON_DOCUMENT

DIRECTOR_TURN_STATUSES = (
    "queued",
    "thinking",
    "awaiting_user",
    "awaiting_execution",
    "completed",
    "failed",
    "cancelled",
    "stale",
)


class DirectorTurn(Base):
    """One idempotent Director request, context snapshot, and text invocation."""

    __tablename__ = "director_turns"
    __table_args__ = (
        UniqueConstraint("project_id", "request_key", name="uq_director_turn_request"),
        CheckConstraint("revision > 0", name="ck_director_turn_revision_positive"),
        CheckConstraint("step_count >= 0", name="ck_director_turn_step_count_nonnegative"),
        CheckConstraint(
            "schema_repair_count >= 0 AND schema_repair_count <= 1",
            name="ck_director_turn_schema_repair_bounded",
        ),
        CheckConstraint(
            "status IN ('queued','thinking','awaiting_user','awaiting_execution',"
            "'completed','failed','cancelled','stale')",
            name="ck_director_turn_status",
        ),
        CheckConstraint(
            "cost_status IN ('unknown','reported')",
            name="ck_director_turn_cost_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    request_key: Mapped[str] = mapped_column(String(200), nullable=False)
    context_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    input_versions: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    intent_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    model_resolution: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    transport_record_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transport_status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    request_summary: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    response_summary: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    token_usage: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    provider_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    cost_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    currency: Mapped[str] = mapped_column(CURRENCY_CODE, nullable=False, default="USD")
    output_hash: Mapped[str | None] = mapped_column(HASH_64, nullable=True)
    output_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    wait_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    proposal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("director_proposals.id", ondelete="SET NULL"), nullable=True
    )
    dispatched_command_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    node_run_ids: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_repair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


Index(
    "ix_director_turns_scope",
    DirectorTurn.__table__.c.project_id,
    DirectorTurn.__table__.c.scope_type,
    DirectorTurn.__table__.c.scope_entity_id,
)
Index(
    "ix_director_turns_status",
    DirectorTurn.__table__.c.project_id,
    DirectorTurn.__table__.c.status,
    DirectorTurn.__table__.c.updated_at,
)


__all__ = ["DIRECTOR_TURN_STATUSES", "DirectorTurn"]
