"""Export / ExportItem ORM (04 export tables, slice fields)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[UUID | None] = mapped_column(nullable=True)
    format: Mapped[str] = mapped_column(String(40), nullable=False, default="timeline_json")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    manifest: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    result_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExportItem(Base):
    __tablename__ = "export_items"
    __table_args__ = (
        UniqueConstraint("export_id", "ordinal", name="uq_export_item_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    export_id: Mapped[UUID] = mapped_column(
        ForeignKey("exports.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
