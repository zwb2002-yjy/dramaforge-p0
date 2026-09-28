"""Archival storage mappings; not a current production or frontend interface.

These tables belong to retained migration history. Only metadata registration
and retention/RLS tests import this module. Current experiments use
ExperimentBranch. Moving the mappings does not drop tables or delete data.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.db_types import JSON_DOCUMENT


class ProductionExperiment(Base):
    """Historical experiment grouping, retained for persisted data only.

    Runtime creation and adoption use ExperimentBranch exclusively.
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
    experiment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="model_swap")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShotExperiment(Base):
    """Historical shot snapshot retained for persisted data only.

    Not a current creation, context, execution or adoption authority.
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
    prompts: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
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
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_shot_experiments_shot", ShotExperiment.__table__.c.shot_id)
