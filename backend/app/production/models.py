"""Versioned Production Graph definitions for controlled media execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.shared.base import Base
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
    source_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    candidate_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    comparison: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    adopted_shot_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
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
    camera: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    characters: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    scene: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
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
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # In-memory / JSON definition body used by app layer (not a free simplified table).
    definition: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
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

