"""Phase 7 Director proposal persistence (03 §64)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base


class DirectorProposal(Base):
    """A Director Assistant proposal grouping typed items (03 §64)."""

    __tablename__ = "director_proposals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_threads.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DirectorProposalItem(Base):
    """One typed, independently acceptable proposal item (03 §64/§67/§68)."""

    __tablename__ = "director_proposal_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("director_proposals.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    expected_target_version: Mapped[int | None] = mapped_column(nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    benefit: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk: Mapped[str] = mapped_column(Text, nullable=False, default="")
    impact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
