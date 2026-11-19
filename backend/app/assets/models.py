"""Canonical Script / Episode / Scene / Shot and versioned Asset models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.assets.knowledge_models import (  # noqa: F401  (registration only)
    KnowledgeEntry,
    KnowledgeRevision,
    KnowledgeSourceLink,
    ProjectKnowledgeReference,
)

# Same-domain leaf module for immutable extraction snapshots; imported here so a
# single models entry registers every asset table for metadata and migrations.
from app.assets.public_asset_models import (  # noqa: F401  (registration only)
    ProjectPublicAssetLink,
    PublicAssetPublication,
    PublicAssetPublicationItem,
)
from app.assets.research_analysis_models import (  # noqa: F401  (registration only)
    ResearchAnalysis,
    ResearchAnalysisInvocation,
    ResearchAnalysisResult,
)
from app.assets.research_models import (  # noqa: F401  (registration only)
    ResearchCitation,
    ResearchResult,
    ResearchResultRevision,
)
from app.assets.source_models import SourceExtraction, SourceFragment  # noqa: F401
from app.assets.source_use_models import (  # noqa: F401  (registration only)
    ArtifactSourceUse,
    SourceUseRevision,
    SourceUseSubject,
)
from app.shared.base import Base
from app.shared.db_types import HASH_64, JSON_DOCUMENT


class ScriptDocument(Base):
    __tablename__ = "script_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="md")
    imported_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("project_id", "episode_number", name="uq_episode_num"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("episode_id", "scene_number", name="uq_scene_num"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    episode_id: Mapped[UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    location_name: Mapped[str] = mapped_column(String(160), nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(40), nullable=False)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    design_state: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Shot(Base):
    __tablename__ = "shots"
    __table_args__ = (UniqueConstraint("scene_id", "shot_number", name="uq_shot_num"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[UUID] = mapped_column(
        ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    shot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    shot_type: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    camera_move: Mapped[str] = mapped_column(String(80), nullable=False, default="static")
    visual_description: Mapped[str] = mapped_column(Text, nullable=False)
    dialogue: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_seconds: Mapped[Decimal] = mapped_column(
        Numeric(8, 3), nullable=False, default=Decimal("3")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    director_state: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    image_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    video_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    formal_keyframe_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "artifacts.id",
            name="fk_shots_formal_keyframe_artifact",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    formal_video_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "artifacts.id",
            name="fk_shots_formal_video_artifact",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    formal_composite_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "artifacts.id",
            name="fk_shots_formal_composite_artifact",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CanvasRevision(Base):
    """Immutable user-visible revision of a shot's formal director canvas."""

    __tablename__ = "canvas_revisions"
    __table_args__ = (
        UniqueConstraint("shot_id", "revision_number", name="uq_canvas_revision_number"),
        CheckConstraint("revision_number > 0", name="ck_canvas_revision_number_positive"),
        CheckConstraint("base_shot_version > 0", name="ck_canvas_revision_base_version_positive"),
        CheckConstraint("duration_seconds > 0", name="ck_canvas_revision_duration_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    base_shot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    visual_description: Mapped[str] = mapped_column(Text, nullable=False)
    shot_type: Mapped[str] = mapped_column(String(40), nullable=False)
    camera_move: Mapped[str] = mapped_column(String(80), nullable=False)
    dialogue: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_seconds: Mapped[Decimal] = mapped_column(
        Numeric(8, 3), nullable=False, default=Decimal("3")
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="user")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShotChangeProposal(Base):
    """A reviewable assistant proposal for a localized shot-canvas change."""

    __tablename__ = "shot_change_proposals"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "idempotency_key", name="uq_shot_change_proposal_idempotency"
        ),
        CheckConstraint(
            "base_shot_version > 0", name="ck_shot_change_proposal_base_version_positive"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    base_shot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    replacement_payload: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    affected_node_keys: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    reusable_artifact_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="awaiting_confirmation")
    confirmed_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canvas_revisions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "name", name="uq_asset_name"),
        CheckConstraint(
            "status IN ('draft','active','recycled')",
            name="ck_assets_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "asset_versions.id",
            name="fk_assets_current_version",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    # Transport-retry identity of the submission that created this card. Null for
    # pre-existing cards and for explicit new operations; the partial unique
    # index only constrains rows that actually carry a key.
    creation_request_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    creation_request_hash: Mapped[str | None] = mapped_column(HASH_64, nullable=True)


class AssetVersion(Base):
    """Immutable project asset card revision used by the professional workspace."""

    __tablename__ = "asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_number", name="uq_asset_version_number"),
        UniqueConstraint("id", "project_id", name="uq_asset_version_scope"),
        CheckConstraint(
            "(base_publication_id IS NULL) = (base_public_asset_link_id IS NULL)",
            name="ck_asset_version_public_base",
        ),
        CheckConstraint(
            "(adoption_request_key IS NULL) = (adoption_request_hash IS NULL) "
            "AND (adoption_request_key IS NULL) = (adopted_asset_revision IS NULL)",
            name="ck_asset_version_adoption_all_or_none",
        ),
        CheckConstraint(
            "(creation_request_key IS NULL) = (creation_request_hash IS NULL)",
            name="ck_asset_version_creation_all_or_none",
        ),
        Index(
            "uq_asset_version_creation_key",
            "project_id",
            "creation_request_key",
            unique=True,
            postgresql_where=text("creation_request_key IS NOT NULL"),
        ),
        Index(
            "uq_asset_version_adoption_key",
            "project_id",
            "adoption_request_key",
            unique=True,
            postgresql_where=text("adoption_request_key IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["base_public_asset_link_id", "project_id", "base_publication_id"],
            [
                "project_public_asset_links.id",
                "project_public_asset_links.project_id",
                "project_public_asset_links.publication_id",
            ],
            name="fk_asset_version_public_base",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint("version_number > 0", name="ck_asset_version_number_positive"),
        CheckConstraint(
            "status IN ('candidate','formal','historical','rejected')",
            name="ck_asset_versions_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    base_publication_id: Mapped[UUID | None] = mapped_column(nullable=True)
    base_public_asset_link_id: Mapped[UUID | None] = mapped_column(nullable=True)
    creation_request_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    creation_request_hash: Mapped[str | None] = mapped_column(HASH_64, nullable=True)
    adoption_request_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    adoption_request_hash: Mapped[str | None] = mapped_column(HASH_64, nullable=True)
    adopted_asset_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AssetVersionReference(Base):
    """Immutable artifact reference pinned to a specific asset version.

    The canonical reference source for execution. References are always pinned
    to an explicit AssetVersion; no name-based or compatibility lookup exists.
    """

    __tablename__ = "asset_version_references"
    __table_args__ = (
        UniqueConstraint(
            "asset_version_id",
            "artifact_id",
            name="uq_asset_version_reference_artifact",
        ),
        UniqueConstraint(
            "id", "asset_version_id", "artifact_id", "project_id",
            name="uq_asset_version_reference_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    reference_role: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AssetTag(Base):
    """Project-scoped tag vocabulary for asset filtering (V1: kind/tags/status/name)."""

    __tablename__ = "asset_tags"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_name", name="uq_asset_tag_project_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AssetTagLink(Base):
    """Many-to-many asset <-> tag link."""

    __tablename__ = "asset_tag_links"

    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_tags.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Indexes are declared explicitly so standalone Alembic metadata retains the
# names and ordering chosen by the historical migrations.
Index(
    "idx_shots_project_scene",
    Shot.__table__.c.project_id,
    Shot.__table__.c.scene_id,
    Shot.__table__.c.shot_number,
)
Index(
    "idx_canvas_revisions_project_shot",
    CanvasRevision.__table__.c.project_id,
    CanvasRevision.__table__.c.shot_id,
    CanvasRevision.__table__.c.revision_number,
)
Index(
    "idx_shot_change_proposals_project_shot",
    ShotChangeProposal.__table__.c.project_id,
    ShotChangeProposal.__table__.c.shot_id,
    ShotChangeProposal.__table__.c.created_at,
)
Index(
    "idx_asset_versions_project_asset",
    AssetVersion.__table__.c.project_id,
    AssetVersion.__table__.c.asset_id,
    AssetVersion.__table__.c.version_number,
)
Index("ix_assets_current_version_id", Asset.__table__.c.current_version_id)
Index(
    "uq_assets_project_creation_request",
    Asset.__table__.c.project_id,
    Asset.__table__.c.creation_request_key,
    unique=True,
    postgresql_where=Asset.__table__.c.creation_request_key.isnot(None),
    sqlite_where=Asset.__table__.c.creation_request_key.isnot(None),
)
Index(
    "ix_shots_formal_keyframe_artifact_id",
    Shot.__table__.c.formal_keyframe_artifact_id,
)
Index(
    "ix_shots_formal_video_artifact_id",
    Shot.__table__.c.formal_video_artifact_id,
)
Index(
    "ix_shots_formal_composite_artifact_id",
    Shot.__table__.c.formal_composite_artifact_id,
)
Index(
    "ix_asset_version_references_version",
    AssetVersionReference.__table__.c.asset_version_id,
)


class ProjectFile(Base):
    """Project-private source association; unlinking preserves every revision."""

    __tablename__ = "project_files"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_project_file_scope"),
        CheckConstraint("version > 0", name="ck_project_files_version"),
        CheckConstraint("content_version > 0", name="ck_project_files_content_version"),
        Index("ix_project_files_project", "project_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    detached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ProjectFileRevision(Base):
    """Original bytes are immutable; extraction is a separately retryable local step."""

    __tablename__ = "project_file_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["file_id", "project_id"], ["project_files.id", "project_files.project_id"],
            name="fk_project_file_revision_scope", ondelete="RESTRICT",
        ),
        # Deferred: the pointer may be set in the same transaction that inserts
        # the extraction, and it can only ever name this revision's own snapshot.
        # ``use_alter`` breaks the extraction <-> revision cycle; the portable
        # unit-test database omits it (the migration owns the PostgreSQL DDL).
        ForeignKeyConstraint(
            ["current_extraction_id", "id", "project_id"],
            [
                "source_extractions.id",
                "source_extractions.file_revision_id",
                "source_extractions.project_id",
            ],
            name="fk_project_file_revision_current_extraction",
            ondelete="NO ACTION", deferrable=True, initially="DEFERRED", use_alter=True,
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["current_analysis_id", "id", "project_id"],
            [
                "research_analyses.id",
                "research_analyses.file_revision_id",
                "research_analyses.project_id",
            ],
            name="fk_project_file_revision_current_analysis",
            ondelete="NO ACTION", deferrable=True, initially="DEFERRED", use_alter=True,
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint("id", "file_id", "project_id", name="uq_project_file_revision_scope"),
        UniqueConstraint("file_id", "number", name="uq_project_file_revision_number"),
        UniqueConstraint("project_id", "request_key", name="uq_project_file_request"),
        CheckConstraint("number > 0", name="ck_project_file_revision_number"),
        CheckConstraint("byte_size >= 0", name="ck_project_file_revision_size"),
        CheckConstraint("attempt > 0", name="ck_project_file_revision_attempt"),
        CheckConstraint(
            "status IN ('pending','parsed','failed')", name="ck_project_file_revision_status",
        ),
        CheckConstraint(
            "processor_profile_revision IS NULL OR length(processor_profile_revision) = 64",
            name="ck_project_file_revision_profile",
        ),
        Index("ix_project_file_revision_hash", "project_id", "content_hash"),
        Index("ix_project_file_revision_pending", "id",
              postgresql_where=text("status = 'pending'"),
              sqlite_where=text("status = 'pending'")),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    file_id: Mapped[UUID] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    error_code: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(80))
    # Frozen at acceptance: the worker must use exactly this processor contract.
    # NULL marks a legacy row accepted before profiles existed; it needs an explicit
    # retry instead of silently running under today's tools.
    processor_profile_revision: Mapped[str | None] = mapped_column(String(64))
    current_extraction_id: Mapped[UUID | None] = mapped_column(nullable=True)
    # Forward-only pointer to the latest published analysis manifest of this revision.
    current_analysis_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
