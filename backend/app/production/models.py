"""Versioned Production Graph definitions for controlled media execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import HASH_64, JSON_DOCUMENT
from app.shared.enums import GraphStatus
from app.shared.errors import ValidationAppError
from app.shared.pg_enums import GRAPH_STATUS, col_enum


class ProductionGraph(Base):
    __tablename__ = "production_graphs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "scope_type",
            "scope_entity_id",
            name="uq_production_graphs_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        col_enum(GRAPH_STATUS), nullable=False, default=GraphStatus.DRAFT.value
    )
    current_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ExperimentBranch(Base):
    """Formal/experimental execution branch kept separate from the official line."""

    __tablename__ = "experiment_branches"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_experiment_branch_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_shot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("shots.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    branch_type: Mapped[str] = mapped_column(String(32), nullable=False, default="model_experiment")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    source_artifact_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    candidate_artifact_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    comparison: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    adopted_shot_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    parameters: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    selected_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DirectorBoardState(Base):
    """Per-shot 2D/rough-3D staging state for camera and performance blocking."""

    __tablename__ = "director_board_states"
    __table_args__ = (UniqueConstraint("shot_id", name="uq_director_board_shot"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="2d")
    camera: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    characters: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    scene: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GraphVersion(Base):
    __tablename__ = "graph_versions"
    __table_args__ = (
        UniqueConstraint("graph_id", "version_number", name="uq_graph_versions_graph_version"),
        UniqueConstraint("graph_id", "definition_hash", name="uq_graph_versions_definition_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    graph_id: Mapped[UUID] = mapped_column(
        ForeignKey("production_graphs.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        col_enum(GRAPH_STATUS), nullable=False, default=GraphStatus.DRAFT.value
    )
    definition_hash: Mapped[str] = mapped_column(HASH_64, nullable=False)
    # In-memory / JSON definition body used by app layer (not a free simplified table).
    definition: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def definition_hash(definition: dict[str, object]) -> str:
    raw = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assert_graph_version_mutable(version: GraphVersion) -> None:
    if version.status in {
        GraphStatus.PUBLISHED.value,
        GraphStatus.SUPERSEDED.value,
        GraphStatus.ARCHIVED.value,
    }:
        raise ValidationAppError("published graph version is immutable")


# Backward-compatible alias used by older imports during transition.
Graph = ProductionGraph



SHOT_REFERENCE_PURPOSES = (
    "identity",
    "clothing",
    "scene_layout",
    "scene_lighting",
    "style",
    "action",
    "pose",
    "camera_language",
    "audio_rhythm",
    "first_frame",
    "last_frame",
    "generic_reference",
)
SHOT_REFERENCE_STAGES = ("image", "video", "both")
SHOT_REFERENCE_RESOLUTION_MODES = ("current_formal", "pinned_version", "direct_artifact")


class ShotReferenceBinding(Base):
    """Business-purpose reference from a shot to an asset/version/artifact.

    The reference stores the *purpose* (identity/clothing/scene_layout/...) not
    a provider role. Prompt ``@name`` text is human-readable only; execution
    resolves this binding to a concrete artifact via ``resolution_mode``.
    """

    __tablename__ = "shot_reference_bindings"
    __table_args__ = (
        CheckConstraint(
            "asset_id IS NOT NULL OR asset_version_id IS NOT NULL OR artifact_id IS NOT NULL",
            name="ck_shot_reference_binding_source",
        ),
        CheckConstraint(
            "(resolution_mode <> 'direct_artifact') OR artifact_id IS NOT NULL",
            name="ck_shot_reference_binding_direct_artifact",
        ),
        CheckConstraint(
            "(resolution_mode <> 'pinned_version') OR asset_version_id IS NOT NULL",
            name="ck_shot_reference_binding_pinned_version",
        ),
        CheckConstraint(
            "(resolution_mode <> 'current_formal') OR asset_id IS NOT NULL",
            name="ck_shot_reference_binding_current_formal",
        ),
        CheckConstraint(
            "stage IN ('image', 'video', 'both')",
            name="ck_shot_reference_binding_stage",
        ),
        CheckConstraint(
            "resolution_mode IN ('current_formal', 'pinned_version', 'direct_artifact')",
            name="ck_shot_reference_binding_resolution_mode",
        ),
        CheckConstraint(
            "purpose IN ('identity', 'clothing', 'scene_layout', 'scene_lighting', "
            "'style', 'action', 'pose', 'camera_language', 'audio_rhythm', "
            "'first_frame', 'last_frame', 'generic_reference')",
            name="ck_shot_reference_binding_purpose",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="RESTRICT"), nullable=False
    )
    shot_experiment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("experiment_branches.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="both")
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True
    )
    asset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="RESTRICT"), nullable=True
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    resolution_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default="current_formal"
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProductionExperiment(Base):
    """Phase 5 project-level A/B experiment grouping shot experiments (03 §45).

    Formal results are never overwritten by an experiment; adoption (P5-06)
    explicitly copies selected results onto the formal line.
    """

    __tablename__ = "production_experiments"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_production_experiment_idempotency",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    experiment_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="model_swap"
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="draft"
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


class ShotExperiment(Base):
    """One shot's A/B experiment inside a :class:`ProductionExperiment` (03 §45).

    Snapshots the source shot's execution inputs (version, director state,
    prompts, references, common controls) and carries per-experiment model
    overrides plus candidate result artifacts. Nothing here mutates the formal
    shot graph.
    """

    __tablename__ = "shot_experiments"
    __table_args__ = (
        UniqueConstraint(
            "production_experiment_id",
            "shot_id",
            name="uq_shot_experiment_shot",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    production_experiment_id: Mapped[UUID] = mapped_column(
        ForeignKey("production_experiments.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    source_shot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    director_state: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    prompts: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    references: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    model_overrides: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    common_controls: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    keyframe_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )
    video_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )
    comparison: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
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


Index(
    "idx_experiment_branches_project",
    ExperimentBranch.__table__.c.project_id,
    ExperimentBranch.__table__.c.created_at,
)
Index("ix_shot_reference_bindings_shot", ShotReferenceBinding.__table__.c.shot_id)
Index("ix_shot_experiments_shot", ShotExperiment.__table__.c.shot_id)
