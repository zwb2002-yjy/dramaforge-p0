"""Source-use declarations: one subject, immutable declared revisions (M03 part 2).

A subject is the stable identity of one private source (a project file revision or
an already-produced artifact). Each revision is an immutable statement of what the
owner declares may be done with it; revocation is a new revision, never an update
of the old one. Artifact provenance rows record which declaration a produced
artifact actually consumed, so later revocation cannot silently rewrite history.
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

SOURCE_USE_STATES = ("unreviewed", "declared", "revoked")
SOURCE_ACCESS_KINDS = ("private", "public_asset", "published_knowledge")
USE_PURPOSES = ("research", "creation", "library_reference", "external_processing", "export")


class SourceUseSubject(Base):
    """Stable identity for one file revision or artifact declaration."""

    __tablename__ = "source_use_subjects"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_source_subject_scope"),
        Index(
            "uq_source_subject_file", "file_revision_id", unique=True,
            postgresql_where=text("file_revision_id IS NOT NULL"),
            sqlite_where=text("file_revision_id IS NOT NULL"),
        ),
        Index(
            "uq_source_subject_artifact", "artifact_id", unique=True,
            postgresql_where=text("artifact_id IS NOT NULL"),
            sqlite_where=text("artifact_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(file_revision_id IS NULL) <> (artifact_id IS NULL)",
            name="ck_source_subject_one_source",
        ),
        CheckConstraint("version > 0", name="ck_source_subject_version"),
        Index("ix_source_subject_project", "project_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False,
    )
    file_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    artifact_id: Mapped[UUID | None] = mapped_column(nullable=True)
    current_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SourceUseRevision(Base):
    """Immutable declaration/revocation body for one subject."""

    __tablename__ = "source_use_revisions"
    __table_args__ = (
        UniqueConstraint("subject_id", "number", name="uq_source_use_revision"),
        UniqueConstraint("subject_id", "origin_expected_version", name="uq_source_use_origin"),
        UniqueConstraint("project_id", "request_key", name="uq_source_use_request"),
        UniqueConstraint(
            "id", "subject_id", "project_id", name="uq_source_use_revision_scope",
        ),
        ForeignKeyConstraint(
            ["subject_id", "project_id"],
            ["source_use_subjects.id", "source_use_subjects.project_id"],
            ondelete="RESTRICT", name="fk_source_use_revision_subject",
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("number > 0", name="ck_source_use_revision_number"),
        CheckConstraint("origin_expected_version > 0", name="ck_source_use_origin_version"),
        CheckConstraint(
            "result_version = origin_expected_version + 1", name="ck_source_use_result_version",
        ),
        CheckConstraint(
            "state IN ('unreviewed','declared','revoked')", name="ck_source_use_state",
        ),
        Index("ix_source_use_revision_subject", "project_id", "subject_id", "number"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    subject_id: Mapped[UUID] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    allowed_uses: Mapped[list[object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    content_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ArtifactSourceUse(Base):
    """Which declaration one produced artifact consumed, at creation time."""

    __tablename__ = "artifact_source_uses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_revision_id", "source_subject_id", "source_project_id"],
            [
                "source_use_revisions.id",
                "source_use_revisions.subject_id",
                "source_use_revisions.project_id",
            ],
            name="fk_artifact_source_use_revision", ondelete="RESTRICT",
            deferrable=True, initially="DEFERRED",
        ),
        UniqueConstraint(
            "artifact_id", "source_subject_id", "input_role", name="uq_artifact_source_use",
        ),
        CheckConstraint(
            "source_access_kind IN ('private','public_asset','published_knowledge')",
            name="ck_artifact_source_access_kind",
        ),
        Index("ix_artifact_source_use_project", "project_id", "artifact_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(nullable=False)
    source_subject_id: Mapped[UUID] = mapped_column(nullable=False)
    source_project_id: Mapped[UUID] = mapped_column(nullable=False)
    source_revision_id: Mapped[UUID] = mapped_column(nullable=False)
    consumer_node_run_id: Mapped[UUID] = mapped_column(nullable=False)
    input_role: Mapped[str] = mapped_column(String(40), nullable=False)
    source_access_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="private", server_default="private",
    )
    access_basis: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict, server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


__all__ = [
    "SOURCE_ACCESS_KINDS",
    "SOURCE_USE_STATES",
    "USE_PURPOSES",
    "ArtifactSourceUse",
    "SourceUseRevision",
    "SourceUseSubject",
]
