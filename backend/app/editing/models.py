"""Phase 9 edit session persistence (03 §82/§84)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base


class EditSession(Base):
    """One project edit session holding a timeline (03 §82).

    The timeline references production lineage (shot ids / artifact ids) as
    read-only provenance; editing never mutates the formal line.
    """

    __tablename__ = "edit_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="Edit")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    timeline: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    production_lineage: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
