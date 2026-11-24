"""Research results, immutable revisions and citations (M04 research, I4-02).

A ``ResearchResult`` is the stable identity of one research finding (six kinds); its
``current_revision_id`` points at the currently effective immutable revision. User
corrections, candidate acceptance and historical restore all append a new revision and
move the pointer forward; no operation rewrites an existing revision. Citations bind a
revision claim to one immutable source fragment of the same project.
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import HASH_64, JSON_DOCUMENT

RESEARCH_KINDS = ("summary", "person", "place", "event", "timeline", "cultural_clue")
RESEARCH_ORIGINS = ("user", "model", "restore", "accept")
RESEARCH_VERIFICATIONS = ("unverified", "corroborated", "user_asserted")


class ResearchResult(Base):
    """Stable research entry; the current pointer is the only mutable fact."""

    __tablename__ = "research_results"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_research_result_scope"),
        # Deferred: the pointer is set in the transaction that inserts the revision.
        ForeignKeyConstraint(
            ["current_revision_id", "id", "project_id"],
            [
                "research_result_revisions.id",
                "research_result_revisions.result_id",
                "research_result_revisions.project_id",
            ],
            name="fk_research_result_current_revision",
            ondelete="NO ACTION", deferrable=True, initially="DEFERRED", use_alter=True,
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "kind IN ('summary','person','place','event','timeline','cultural_clue')",
            name="ck_research_result_kind",
        ),
        CheckConstraint("version > 0", name="ck_research_result_version"),
        Index("ix_research_result_project", "project_id", "kind", "archived_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    current_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ResearchResultRevision(Base):
    """One immutable content snapshot; only the parent result's pointer moves."""

    __tablename__ = "research_result_revisions"
    __table_args__ = (
        UniqueConstraint("result_id", "number", name="uq_research_revision_number"),
        UniqueConstraint("project_id", "request_key", name="uq_research_revision_request"),
        UniqueConstraint("id", "result_id", "project_id", name="uq_research_revision_scope"),
        UniqueConstraint("id", "project_id", name="uq_research_revision_project"),
        UniqueConstraint(
            "result_id", "applied_result_version", name="uq_research_revision_applied",
        ),
        UniqueConstraint(
            "id", "result_id", "project_id", "applied_result_version",
            name="uq_research_revision_applied_scope",
        ),
        Index(
            "uq_research_revision_invocation_item",
            "origin_invocation_id",
            "output_item_key",
            unique=True,
            postgresql_where=text("origin_invocation_id IS NOT NULL"),
            sqlite_where=text("origin_invocation_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["result_id", "project_id"],
            ["research_results.id", "research_results.project_id"],
            ondelete="RESTRICT", name="fk_research_revision_result",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["base_revision_id", "result_id", "project_id"],
            [
                "research_result_revisions.id",
                "research_result_revisions.result_id",
                "research_result_revisions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_revision_base",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["restores_revision_id", "result_id", "project_id"],
            [
                "research_result_revisions.id",
                "research_result_revisions.result_id",
                "research_result_revisions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_revision_restores",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["accepts_revision_id", "result_id", "project_id"],
            [
                "research_result_revisions.id",
                "research_result_revisions.result_id",
                "research_result_revisions.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_revision_accepts",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["origin_invocation_id", "project_id"],
            ["director_invocations.id", "director_invocations.project_id"],
            ondelete="RESTRICT", name="fk_research_revision_invocation",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("number > 0", name="ck_research_revision_number"),
        CheckConstraint(
            "origin IN ('user','model','restore','accept')", name="ck_research_revision_origin",
        ),
        CheckConstraint(
            "verification IN ('unverified','corroborated','user_asserted')",
            name="ck_research_revision_verification",
        ),
        CheckConstraint(
            "applied_result_version IS NULL OR applied_result_version > 1",
            name="ck_research_revision_applied_version",
        ),
        CheckConstraint(
            "(origin = 'model' AND origin_invocation_id IS NOT NULL "
            "AND output_item_key IS NOT NULL) "
            "OR (origin <> 'model' AND origin_invocation_id IS NULL "
            "AND output_item_key IS NULL)",
            name="ck_research_revision_invocation_origin",
        ),
        CheckConstraint(
            "(origin = 'restore' AND restores_revision_id IS NOT NULL) "
            "OR (origin <> 'restore' AND restores_revision_id IS NULL)",
            name="ck_research_revision_restores_origin",
        ),
        CheckConstraint(
            "(origin = 'accept' AND accepts_revision_id IS NOT NULL) "
            "OR (origin <> 'accept' AND accepts_revision_id IS NULL)",
            name="ck_research_revision_accepts_origin",
        ),
        Index("ix_research_revision_result", "project_id", "result_id", "number"),
        Index(
            "ix_research_revision_search",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    result_id: Mapped[UUID] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    content_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    verification: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified", server_default="unverified",
    )
    base_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    restores_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    accepts_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    applied_result_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_invocation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    output_item_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    search_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ResearchCitation(Base):
    """Verbatim evidence binding one revision claim to one immutable fragment."""

    __tablename__ = "research_citations"
    __table_args__ = (
        UniqueConstraint(
            "research_revision_id", "claim_key", "source_fragment_id",
            name="uq_research_citation_claim",
        ),
        ForeignKeyConstraint(
            ["research_revision_id", "project_id"],
            ["research_result_revisions.id", "research_result_revisions.project_id"],
            ondelete="RESTRICT", name="fk_research_citation_revision",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["source_fragment_id", "file_revision_id", "project_id"],
            [
                "source_fragments.id",
                "source_fragments.file_revision_id",
                "source_fragments.project_id",
            ],
            ondelete="RESTRICT", name="fk_research_citation_fragment",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("claim_key <> ''", name="ck_research_citation_claim_key"),
        Index(
            "ix_research_citation_fragment", "project_id", "file_revision_id",
            "research_revision_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    research_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    source_fragment_id: Mapped[UUID] = mapped_column(nullable=False)
    file_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    claim_key: Mapped[str] = mapped_column(
        String(120), nullable=False, default="root", server_default="root",
    )
    locator_override: Mapped[dict[str, object] | None] = mapped_column(
        JSON_DOCUMENT, nullable=True,
    )
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


__all__ = [
    "RESEARCH_KINDS",
    "RESEARCH_ORIGINS",
    "RESEARCH_VERIFICATIONS",
    "ResearchCitation",
    "ResearchResult",
    "ResearchResultRevision",
]
