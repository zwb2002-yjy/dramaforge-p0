"""P5-03 Experiment creation service (03 §47).

Creates a :class:`ProductionExperiment` with one :class:`ShotExperiment` per
target shot, snapshotting the formal shot's execution inputs (version, director
state, prompts, references, common controls) so an A/B experiment never mutates
the formal shot.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.assets.models import Shot
from app.production.models import (
    ProductionExperiment,
    ShotExperiment,
)
from app.shared.errors import ValidationAppError


class ExperimentCreateInput(BaseModel):
    """Inputs for creating a Phase 5 experiment (03 §47)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    shot_ids: list[UUID] = Field(default_factory=list)
    scene_id: UUID | None = None
    experiment_type: str = Field(default="model_swap", max_length=32)
    model_overrides: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=160)


class ExperimentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_experiment(
        self,
        *,
        project: Project,
        actor: User,
        experiment_input: ExperimentCreateInput,
    ) -> ProductionExperiment:
        """Create a project experiment with per-shot snapshots."""
        shot_ids = list(experiment_input.shot_ids)
        if experiment_input.scene_id is not None:
            scene_shots = (
                await self._session.execute(
                    select(Shot)
                    .where(
                        Shot.project_id == project.id,
                        Shot.scene_id == experiment_input.scene_id,
                    )
                    .order_by(Shot.shot_number)
                )
            ).scalars().all()
            if shot_ids:
                wanted = set(shot_ids)
                scene_shots = [s for s in scene_shots if s.id in wanted]
            shot_ids = [s.id for s in scene_shots]
        if not shot_ids:
            raise ValidationAppError(
                "experiment requires at least one shot",
                details={"code": "EXPERIMENT_NO_SHOTS"},
            )

        existing = await self._session.scalar(
            select(ProductionExperiment).where(
                ProductionExperiment.project_id == project.id,
                ProductionExperiment.idempotency_key == experiment_input.idempotency_key,
            )
        )
        if existing is not None:
            return existing

        experiment = ProductionExperiment(
            project_id=project.id,
            name=experiment_input.name,
            idempotency_key=experiment_input.idempotency_key,
            experiment_type=experiment_input.experiment_type,
            status="draft",
            created_by=actor.id,
        )
        self._session.add(experiment)
        await self._session.flush()

        for shot_id in shot_ids:
            shot = await self._session.get(Shot, shot_id)
            if shot is None or shot.project_id != project.id:
                raise ValidationAppError(
                    "shot not found in project",
                    details={"code": "SHOT_NOT_FOUND"},
                )
            references = await self._shot_references(project.id, shot_id)
            shot_exp = ShotExperiment(
                production_experiment_id=experiment.id,
                project_id=project.id,
                shot_id=shot.id,
                source_shot_version=shot.version,
                director_state=dict(shot.director_state or {}),
                prompts={
                    "image_prompt": shot.image_prompt,
                    "video_prompt": shot.video_prompt,
                },
                references=references,
                model_overrides=dict(experiment_input.model_overrides),
                common_controls={
                    "aspect_ratio": project.aspect_ratio,
                },
                status="draft",
                created_by=actor.id,
            )
            self._session.add(shot_exp)
        await self._session.flush()
        return experiment

    async def _shot_references(self, project_id: UUID, shot_id: UUID) -> list[dict[str, object]]:
        from app.production.models import ShotReferenceBinding

        rows = (
            await self._session.execute(
                select(ShotReferenceBinding)
                .where(
                    ShotReferenceBinding.project_id == project_id,
                    ShotReferenceBinding.shot_id == shot_id,
                )
                .order_by(ShotReferenceBinding.sort_order)
            )
        ).scalars().all()
        return [
            {
                "purpose": row.purpose,
                "resolution_mode": row.resolution_mode,
                "asset_id": str(row.asset_id) if row.asset_id else None,
                "asset_version_id": str(row.asset_version_id) if row.asset_version_id else None,
                "artifact_id": str(row.artifact_id) if row.artifact_id else None,
                "label": row.label,
            }
            for row in rows
        ]
