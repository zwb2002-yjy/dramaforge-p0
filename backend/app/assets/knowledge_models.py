"""Independent cultural knowledge: entries, immutable revisions and project references.

Knowledge belongs to the current user across all their Workspaces (N05); it does not
require a Project. Published content is an explicitly selected immutable snapshot; the
project research that informed it stays private. Private source links are readable only
through the originating project, never serialized into cross-project read models.
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

KNOWLEDGE_KINDS = ("summary", "person", "place", "event", "timeline", "cultural_clue")
KNOWLEDGE_STATUSES = ("draft", "published", "withdrawn")
KNOWLEDGE_OPERATIONS = ("save_draft", "publish", "withdraw")


class KnowledgeEntry(Base):
    """Stable knowledge identity owned by one user; only the pointer/status move."""

    __tablename__ = "knowledge_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_entry_workspace",
        ),
        UniqueConstraint("id", "owner_user_id", name="uq_knowledge_entry_owner"),
        ForeignKeyConstraint(
            ["current_revision_id", "id", "owner_user_id"],
            [
                "knowledge_revisions.id",
                "knowledge_revisions.entry_id",
                "knowledge_revisions.owner_user_id",
            ],
            name="fk_knowledge_entry_current_revision",
            ondelete="NO ACTION", deferrable=True, initially="DEFERRED", use_alter=True,
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "kind IN ('summary','person','place','event','timeline','cultural_clue')",
            name="ck_knowledge_entry_kind",
        ),
        CheckConstraint(
            "publication_status IN ('draft','published','withdrawn')",
            name="ck_knowledge_entry_status",
        ),
        CheckConstraint(
            "(publication_status = 'withdrawn') = (withdrawn_at IS NOT NULL)",
            name="ck_knowledge_entry_withdrawn",
        ),
        CheckConstraint("version > 0", name="ck_knowledge_entry_version"),
        Index("ix_knowledge_entry_owner", "owner_user_id", "publication_status", "kind", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    current_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    publication_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class KnowledgeRevision(Base):
    """Immutable knowledge snapshot for one explicit user decision."""

    __tablename__ = "knowledge_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["entry_id", "owner_user_id"],
            ["knowledge_entries.id", "knowledge_entries.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_revision_entry",
            deferrable=True, initially="DEFERRED",
        ),
        UniqueConstraint("entry_id", "number", name="uq_knowledge_revision_number"),
        UniqueConstraint("owner_user_id", "request_key", name="uq_knowledge_revision_request"),
        UniqueConstraint(
            "id", "entry_id", "owner_user_id", name="uq_knowledge_revision_scope",
        ),
        UniqueConstraint("id", "owner_user_id", name="uq_knowledge_revision_owner"),
        UniqueConstraint(
            "entry_id", "result_entry_version", name="uq_knowledge_revision_result",
        ),
        CheckConstraint("number > 0", name="ck_knowledge_revision_number"),
        CheckConstraint("expected_entry_version > 0", name="ck_knowledge_expected_version"),
        CheckConstraint("result_entry_version > 1", name="ck_knowledge_result_version"),
        CheckConstraint(
            "result_entry_version = expected_entry_version + 1",
            name="ck_knowledge_result_increment",
        ),
        CheckConstraint(
            "operation IN ('save_draft','publish','withdraw')",
            name="ck_knowledge_revision_operation",
        ),
        CheckConstraint(
            "publication_status IN ('draft','published','withdrawn')",
            name="ck_knowledge_revision_status",
        ),
        CheckConstraint(
            "(operation = 'save_draft' AND publication_status = 'draft') "
            "OR (operation = 'publish' AND publication_status = 'published') "
            "OR (operation = 'withdraw' AND publication_status = 'withdrawn')",
            name="ck_knowledge_operation_status",
        ),
        Index("ix_knowledge_revision_entry", "owner_user_id", "entry_id", "number"),
        Index(
            "ix_knowledge_revision_search",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(nullable=False)
    entry_id: Mapped[UUID] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    content_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    allowed_uses: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    public_source_notes: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    publication_status: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_entry_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_entry_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    search_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class KnowledgeSourceLink(Base):
    """Private provenance link from one knowledge revision to project research."""

    __tablename__ = "knowledge_source_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_project",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_workspace",
        ),
        ForeignKeyConstraint(
            ["research_revision_id", "project_id"],
            ["research_result_revisions.id", "research_result_revisions.project_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_research",
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["knowledge_revision_id", "owner_user_id"],
            ["knowledge_revisions.id", "knowledge_revisions.owner_user_id"],
            ondelete="RESTRICT", name="fk_knowledge_source_revision",
            deferrable=True, initially="DEFERRED",
        ),
        UniqueConstraint(
            "knowledge_revision_id", "research_revision_id",
            name="uq_knowledge_source_link",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(nullable=False)
    research_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    knowledge_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ProjectKnowledgeReference(Base):
    """One project's fixed reference to one published knowledge revision."""

    __tablename__ = "project_knowledge_references"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT", name="fk_project_knowledge_reference_project",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "owner_user_id"],
            ["workspaces.id", "workspaces.owner_user_id"],
            ondelete="RESTRICT", name="fk_project_knowledge_reference_workspace",
        ),
        ForeignKeyConstraint(
            ["knowledge_revision_id", "knowledge_entry_id", "owner_user_id"],
            [
                "knowledge_revisions.id",
                "knowledge_revisions.entry_id",
                "knowledge_revisions.owner_user_id",
            ],
            ondelete="RESTRICT", name="fk_project_knowledge_reference_revision",
            deferrable=True, initially="DEFERRED",
        ),
        UniqueConstraint(
            "project_id", "knowledge_revision_id", "allowed_use",
            name="uq_project_knowledge_reference",
        ),
        CheckConstraint("version > 0", name="ck_project_knowledge_reference_version"),
        Index(
            "ix_project_knowledge_reference_project", "project_id", "detached_at", "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(nullable=False)
    knowledge_entry_id: Mapped[UUID] = mapped_column(nullable=False)
    knowledge_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    allowed_use: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    detached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


__all__ = [
    "KNOWLEDGE_KINDS",
    "KNOWLEDGE_OPERATIONS",
    "KNOWLEDGE_STATUSES",
    "KnowledgeEntry",
    "KnowledgeRevision",
    "KnowledgeSourceLink",
    "ProjectKnowledgeReference",
]
