"""Script / Episode / Scene / Shot / Character models (field-faithful subset of `04`)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base


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
        JSON, nullable=False, default=dict
    )
    affected_node_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reusable_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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
    __table_args__ = (UniqueConstraint("project_id", "kind", "name", name="uq_asset_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AssetVersion(Base):
    """Immutable project asset card revision used by the professional workspace."""

    __tablename__ = "asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_number", name="uq_asset_version_number"),
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
        "metadata", JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    locked_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    calibration_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")


class CharacterReference(Base):
    __tablename__ = "character_references"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reference_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="canonical")
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
