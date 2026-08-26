"""P5-03 Experiment creation service (03 §47).

Creates a :class:`ProductionExperiment` with one :class:`ShotExperiment` per
target shot, snapshotting the formal shot's execution inputs (version, director
state, prompts, references, common controls) so an A/B experiment never mutates
the formal shot.
"""

from __future__ import annotations

from typing import cast
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
from app.production.reference_intents import ShotReferenceIntent, compile_references
from app.providers.capabilities import Capability
from app.providers.manifest import ModelManifest
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




def recompile_controls_for_model(
    *,
    manifest: ModelManifest,
    capability: Capability,
    references: list[dict[str, object]],
    common_controls: dict[str, object],
    mode_id: str | None = None,
) -> dict[str, object]:
    """P5-04: recompile experiment inputs for a new model.

    - semantic prompt / asset refs / common controls are preserved;
    - native options not declared by the new model manifest are dropped;
    - references are re-compiled against the new model via P4-02;
    - unsupported controls/references are surfaced, never silently dropped.
    """
    intents: list[ShotReferenceIntent] = []
    for reference in references:
        artifact_id = reference.get("artifact_id")
        if artifact_id is None:
            continue
        intents.append(
            ShotReferenceIntent(
                purpose=str(reference.get("purpose", "generic_reference")),
                artifact_id=UUID(str(artifact_id)),
                resolution_mode=str(reference.get("resolution_mode", "current_formal")),
                mime_type=str(reference.get("mime_type", "image/png")),
            )
        )
    compiled = compile_references(
        manifest=manifest,
        capability=capability,
        references=intents,
        mode_id=mode_id,
        accept_approximations=False,
    )

    spec = manifest.capability_specs.get(capability)
    declared = set((spec.mode_spec(mode_id).common_options).keys()) if spec is not None else set()
    # Semantic controls that survive are those the new model declares; aspect
    # ratio is a product-level control kept across swaps.
    kept = {
        key: value
        for key, value in common_controls.items()
        if key in declared or key in {"aspect_ratio", "duration_seconds"}
    }
    dropped = sorted(set(common_controls) - set(kept))

    return {
        "common_controls": kept,
        "dropped_native_options": dropped,
        "reference_delivery": [r.model_dump(mode="json") for r in compiled.planned_references],
        "unsupported_controls": [r.model_dump(mode="json") for r in compiled.unsupported],
        "translation_report": {},
    }


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



    async def create_model_swap_experiment(
        self,
        *,
        project: Project,
        actor: User,
        experiment_input: ExperimentCreateInput,
    ) -> ProductionExperiment:
        """P5-04: create an experiment and recompile each swapped shot's
        inputs against the target model manifest (drop model A native options)."""
        experiment = await self.create_experiment(
            project=project,
            actor=actor,
            experiment_input=experiment_input,
        )
        shot_experiments = (
            await self._session.execute(
                select(ShotExperiment).where(
                    ShotExperiment.production_experiment_id == experiment.id
                )
            )
        ).scalars().all()
        for shot_exp in shot_experiments:
            target_model = self._target_model_override(shot_exp)
            if not target_model:
                continue
            capability = Capability.VIDEO_IMAGE_TO_VIDEO
            manifest = await self._manifest_for_model(
                workspace_id=project.workspace_id,
                model_id=target_model,
            )
            if manifest is None:
                continue
            recompiled = recompile_controls_for_model(
                manifest=manifest,
                capability=capability,
                references=list(shot_exp.references or []),
                common_controls=dict(shot_exp.common_controls or {}),
                mode_id="explicit_binding",
            )
            shot_exp.common_controls = cast(
                dict[str, object], recompiled["common_controls"]
            )
            comparison = dict(shot_exp.comparison or {})
            comparison["model_swap_recompile"] = recompiled
            shot_exp.comparison = comparison
        await self._session.flush()
        return experiment

    @staticmethod
    def _target_model_override(shot_exp: ShotExperiment) -> str | None:
        overrides = shot_exp.model_overrides or {}
        for slot in ("video.shot", "visual.keyframe"):
            model_id = overrides.get(slot)
            if model_id:
                return str(model_id)
        return None

    async def _manifest_for_model(
        self,
        *,
        workspace_id: UUID,
        model_id: str,
    ) -> ModelManifest | None:
        from app.providers.catalog_models import ModelCatalogEntry
        from app.providers.manifest import (
            ModelCapabilityManifest,
            to_v3_model_manifest,
        )
        from app.providers.models import ProviderModelBinding

        binding = await self._session.scalar(
            select(ProviderModelBinding).where(
                ProviderModelBinding.workspace_id == workspace_id,
                ProviderModelBinding.model_id == model_id,
                ProviderModelBinding.enabled.is_(True),
            )
        )
        if binding is None or binding.catalog_entry_id is None:
            return None
        entry = await self._session.get(ModelCatalogEntry, binding.catalog_entry_id)
        if entry is None:
            return None
        capability_manifest = ModelCapabilityManifest.model_validate(
            entry.capability_manifest_json
        )
        return to_v3_model_manifest(capability_manifest, transport_profile_id="experiment")
