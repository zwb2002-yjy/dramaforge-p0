"""Published research analysis manifests (I4-02).

An analysis row only exists after one completed local research run published its
manifest: six category outcomes, coverage and the exact invocations that produced it.
Results link each new or candidate research revision to the analysis; the file revision
keeps a forward-only ``current_analysis_id`` pointer. No analysis job/queue row exists.
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
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import HASH_64, JSON_DOCUMENT

RESEARCH_CATEGORY_OUTCOMES = ("findings", "none", "incomplete")


class ResearchAnalysis(Base):
    """Immutable published manifest of one completed research analysis."""

    __tablename__ = "research_analyses"
    __table_args__ = (
        UniqueConstraint("project_id", "request_key", name="uq_research_analysis_request"),
        UniqueConstraint(
            "id", "file_revision_id", "project_id", name="uq_research_analysis_revision_scope",
        ),
        UniqueConstraint("id", "project_id", name="uq_research_analysis_scope"),
        ForeignKeyConstraint(
            ["source_extraction_id", "file_revision_id", "project_id"],
            [
                "source_extractions.id",
                "source_extractions.file_revision_id",
                "source_extractions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_analysis_extraction",
            deferrable=True, initially="DEFERRED",
        ),
        Index(
            "ix_research_analysis_revision",
            "project_id", "file_revision_id", "completed_at", "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    file_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    source_extraction_id: Mapped[UUID] = mapped_column(nullable=False)
    coverage: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    category_outcomes: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ResearchAnalysisInvocation(Base):
    """Which Director invocations the manifest actually consumed."""

    __tablename__ = "research_analysis_invocations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "analysis_id", "invocation_id", name="pk_research_analysis_invocation",
        ),
        UniqueConstraint("analysis_id", "ordinal", name="uq_research_analysis_invocation_ordinal"),
        ForeignKeyConstraint(
            ["analysis_id", "project_id"],
            ["research_analyses.id", "research_analyses.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_invocation_analysis",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["invocation_id", "project_id"],
            ["director_invocations.id", "director_invocations.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_invocation_invocation",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("ordinal >= 0", name="ck_research_analysis_invocation_ordinal"),
    )

    analysis_id: Mapped[UUID] = mapped_column(nullable=False)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    invocation_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class ResearchAnalysisResult(Base):
    """One new or candidate research revision published by one analysis category."""

    __tablename__ = "research_analysis_results"
    __table_args__ = (
        PrimaryKeyConstraint(
            "analysis_id", "research_revision_id", name="pk_research_analysis_result",
        ),
        UniqueConstraint(
            "analysis_id", "category", "ordinal", name="uq_research_analysis_result_ordinal",
        ),
        ForeignKeyConstraint(
            ["analysis_id", "project_id"],
            ["research_analyses.id", "research_analyses.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_result_analysis",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["research_revision_id", "project_id"],
            ["research_result_revisions.id", "research_result_revisions.project_id"],
            ondelete="RESTRICT", name="fk_research_analysis_result_revision",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint(
            "category IN ('summary','person','place','event','timeline','cultural_clue')",
            name="ck_research_analysis_result_category",
        ),
        CheckConstraint("ordinal >= 0", name="ck_research_analysis_result_ordinal"),
    )

    analysis_id: Mapped[UUID] = mapped_column(nullable=False)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    research_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = [
    "RESEARCH_CATEGORY_OUTCOMES",
    "ResearchAnalysis",
    "ResearchAnalysisInvocation",
    "ResearchAnalysisResult",
]
