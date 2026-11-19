"""Immutable source extraction snapshots (M04); loaded by ``app.assets.models``.

A successful extraction is append-only evidence. Reprocessing appends a new
Extraction with new Fragments; the revision's ``current_extraction_id`` pointer
only ever moves forward through CAS, and older research citations keep reading
the exact snapshot they were created against.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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

LOCATOR_KINDS = ("paragraph", "page_region", "image_region", "time_range", "table_cells")
EXTRACTION_METHODS = ("native_text", "ocr", "transcript", "visual_input", "metadata")


class SourceExtraction(Base):
    """One completed local parse of one immutable revision attempt."""

    __tablename__ = "source_extractions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["file_revision_id", "file_id", "project_id"],
            [
                "project_file_revisions.id",
                "project_file_revisions.file_id",
                "project_file_revisions.project_id",
            ],
            name="fk_source_extraction_revision_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("file_revision_id", "attempt", name="uq_source_extraction_attempt"),
        UniqueConstraint(
            "id", "file_revision_id", "project_id", name="uq_source_extraction_scope",
        ),
        CheckConstraint("attempt > 0", name="ck_source_extraction_attempt"),
        CheckConstraint(
            "extraction_schema_version > 0", name="ck_source_extraction_schema_version",
        ),
        Index(
            "ix_source_extraction_revision",
            "project_id",
            "file_revision_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    file_id: Mapped[UUID] = mapped_column(nullable=False)
    file_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_key: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    extraction_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    processor_evidence: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict,
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class SourceFragment(Base):
    """Addressable text span inside one immutable extraction."""

    __tablename__ = "source_fragments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_id", "file_revision_id", "project_id"],
            [
                "source_extractions.id",
                "source_extractions.file_revision_id",
                "source_extractions.project_id",
            ],
            name="fk_source_fragment_extraction_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("extraction_id", "ordinal", name="uq_source_fragment_ordinal"),
        UniqueConstraint("id", "file_revision_id", "project_id", name="uq_source_fragment_scope"),
        CheckConstraint("ordinal >= 0", name="ck_source_fragment_ordinal"),
        CheckConstraint(
            "locator_kind IN ('paragraph','page_region','image_region','time_range','table_cells')",
            name="ck_source_fragment_locator_kind",
        ),
        CheckConstraint(
            "extraction_method IN "
            "('native_text','ocr','transcript','visual_input','metadata')",
            name="ck_source_fragment_extraction_method",
        ),
        Index(
            "ix_source_fragment_revision", "project_id", "file_revision_id", "ordinal",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    extraction_id: Mapped[UUID] = mapped_column(nullable=False)
    file_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    locator_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    locator: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(24), nullable=False)
    processor_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_meta: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


__all__ = ["EXTRACTION_METHODS", "LOCATOR_KINDS", "SourceExtraction", "SourceFragment"]
