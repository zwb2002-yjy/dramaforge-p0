"""Authenticated read-only model/compile/snapshot application seam.

HTTP and future Director tools share this service; neither gets a production
writer, credential decryptor, object-store reader or provider runtime.
"""

from __future__ import annotations

import hashlib
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.production.workbench_execution import WorkbenchExecutionInput, WorkbenchExecutionService
from app.providers.capabilities import Capability
from app.providers.capability_inspection import (
    ModelCapabilityReport,
    inspect_catalog_model,
    inspect_manifest,
)
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import hash_manifest
from app.providers.compile_preview import CompilePreview, PreviewReference, preview_compile
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.service import default_model_registry
from app.providers.model_profiles.slots import MODEL_SLOT_DEFINITIONS, ModelSlot
from app.providers.model_resolution import ExecutionModelResolver
from app.shared.errors import NotFoundError, ValidationAppError

Stage = Literal["image_keyframe", "video"]
_STAGE = {
    "image_keyframe": (ModelSlot.VISUAL_KEYFRAME, Capability.IMAGE_GENERATE, "keyframe"),
    "video": (ModelSlot.VIDEO_SHOT, Capability.VIDEO_IMAGE_TO_VIDEO, "video"),
}


class ModelQueryRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    selection: Literal["explicit_catalog", "current_binding", "text_slot"]
    report: ModelCapabilityReport
    binding_id: UUID | None = None
    profile_version: int | None = None
    mode_id: str | None = None
    identity_hash: str | None = None


class GenerationCompileRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_fingerprint: str
    snapshot_hash: str
    model: ModelCapabilityReport
    compilation: CompilePreview
    observed_versions: dict[str, int]
    reference_plan: list[PreviewReference]
    warnings: list[str] = Field(default_factory=list)


class GenerationSnapshotRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    shot_id: UUID
    status: str
    input_hash: str
    plan_fingerprint: str | None = None
    prompt_hash: str | None = None
    requested_model_id: str | None = None
    planned_model_id: str | None = None
    compiled_models: list[str] = Field(default_factory=list)
    compiled_options: list[dict[str, JsonValue]] = Field(default_factory=list)
    operation_ids: list[UUID] = Field(default_factory=list)
    compiled_request_hashes: list[str] = Field(default_factory=list)
    operation_statuses: list[str] = Field(default_factory=list)
    reference_plan: list[PreviewReference] = Field(default_factory=list)
    artifact_id: UUID | None = None
    artifact_hash: str | None = None
    observed_output: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_missing: list[str] = Field(default_factory=list)


def _compiled_options(summary: dict[str, object]) -> dict[str, JsonValue]:
    import re

    effective = summary.get("effective_request")
    options = effective.get("common_options") if isinstance(effective, dict) else None
    if not isinstance(options, dict):
        return {}
    allowed = {
        "size",
        "aspect_ratio",
        "duration_seconds",
        "resolution",
        "seed",
        "width",
        "height",
        "num_frames",
        "frame_rate",
        "generate_audio",
        "n",
    }
    return {
        str(key): value
        for key, value in options.items()
        if key in allowed
        and (
            isinstance(value, (int, float, bool))
            or isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9.:_-]{1,64}", value)
        )
    }


class ModelInspectionService:
    def __init__(self, session: AsyncSession, *, actor: User) -> None:
        self._session = session
        self._actor = actor

    async def _project(self, project_id: UUID) -> Project:
        return await ProjectService(self._session).get_project_for_owner(
            project_id=project_id,
            actor=self._actor,
        )

    async def _shot(self, project_id: UUID, shot_id: UUID) -> Shot:
        shot = await self._session.scalar(
            select(Shot).where(
                Shot.id == shot_id,
                Shot.project_id == project_id,
            )
        )
        if shot is None:
            raise NotFoundError("shot not found")
        return shot

    async def _catalog(self, entry_id: UUID | None) -> ModelCapabilityManifest:
        entry = await self._session.get(ModelCatalogEntry, entry_id) if entry_id else None
        if entry is None:
            raise NotFoundError("resolved catalog not found")
        if hash_manifest(entry.capability_manifest_json) != entry.contract_manifest_hash:
            raise ValidationAppError("catalog manifest identity mismatch")
        return ModelCapabilityManifest.model_validate(entry.capability_manifest_json)

    async def get_model_capabilities(
        self,
        *,
        project_id: UUID,
        model_id: str | None = None,
        stage: Stage | None = None,
        slot: ModelSlot | None = None,
        mode_id: str | None = None,
    ) -> ModelQueryRead:
        project = await self._project(project_id)
        if sum(value is not None for value in (model_id, stage, slot)) != 1:
            raise ValidationAppError("provide exactly one of model_id, stage or text slot")
        if model_id is not None:
            report = inspect_catalog_model(model_id, registry=default_model_registry())
            result = ModelQueryRead(selection="explicit_catalog", report=report, mode_id=mode_id)
        elif stage is not None:
            model_slot, capability, purpose = _STAGE[stage]
            resolution = await ExecutionModelResolver(self._session).resolve(
                project=project,
                slot=model_slot,
                capability=capability,
                purpose=purpose,
                mode_id=mode_id,
            )
            if resolution.status != "RESOLVED":
                raise ValidationAppError(
                    "current model binding unavailable",
                    details={
                        "code": "MODEL_BINDING_UNAVAILABLE",
                    },
                )
            catalog = await self._catalog(resolution.catalog_entry_id)
            manifest = to_v3_model_manifest(catalog, transport_profile_id="inspection")
            result = ModelQueryRead(
                selection="current_binding",
                report=inspect_manifest(manifest, catalog=catalog),
                binding_id=resolution.provider_model_binding_id,
                mode_id=mode_id,
                identity_hash=hash_manifest(resolution.model_dump(mode="json")),
            )
        else:
            assert slot is not None
            if Capability.TEXT_GENERATE not in MODEL_SLOT_DEFINITIONS[slot].required_capabilities:
                raise ValidationAppError("use stage for a current media binding")
            registry = default_model_registry()
            resolution_text = await ModelBindingResolver(self._session, registry).resolve(
                workspace_id=project.workspace_id,
                project_id=project.id,
                slot=slot,
                capability=Capability.TEXT_GENERATE,
            )
            result = ModelQueryRead(
                selection="text_slot",
                report=inspect_catalog_model(resolution_text.model_id, registry=registry),
                profile_version=resolution_text.profile_version,
                identity_hash=hash_manifest(resolution_text.model_dump(mode="json")),
            )
        if mode_id is not None:
            # Validate declared modes rather than treating an unknown mode as default.
            for spec in result.report.capabilities.values():
                if (spec.modes and mode_id not in spec.modes) or (
                    not spec.modes and mode_id not in {"legacy", "explicit_binding"}
                ):
                    raise ValidationAppError("model input mode is not declared")
        return result

    async def preview_generation_compile(
        self,
        *,
        project_id: UUID,
        request: WorkbenchExecutionInput,
    ) -> GenerationCompileRead:
        project = await self._project(project_id)
        if request.project_id != project_id or request.accept_approximations:
            raise ValidationAppError("preview cannot change scope or accept approximations")
        shot = await self._shot(project_id, request.shot_id)
        if request.expected_shot_version is None or shot.version != request.expected_shot_version:
            raise ValidationAppError("shot version changed", details={"code": "CONTEXT_STALE"})
        with self._session.no_autoflush:
            plan = await WorkbenchExecutionService(
                self._session, user_id=self._actor.id
            ).build_plan(
                project=project,
                execution_input=request,
                allow_unaccepted_approximations=True,
            )
            catalog = await self._catalog(plan.resolved_model.catalog_entry_id)
            refs: list[PreviewReference] = []
            for reference in plan.planned_references:
                artifact = await self._session.scalar(
                    select(Artifact).where(
                        Artifact.id == reference.artifact_id,
                        Artifact.project_id == project_id,
                        Artifact.storage_state == "available",
                        Artifact.deleted_at.is_(None),
                    )
                )
                if artifact is None or reference.role is None:
                    raise ValidationAppError("reference metadata unavailable")
                if reference.fingerprint and reference.fingerprint != artifact.content_hash:
                    raise ValidationAppError("reference fingerprint changed")
                refs.append(
                    PreviewReference.model_validate(
                        {
                            "role": reference.role,
                            "artifact_id": artifact.id,
                            "fingerprint": artifact.content_hash,
                            "mime_type": artifact.mime_type,
                        }
                    )
                )
            selection = ModelSelectionIntent(
                mode="explicit_binding",
                model_binding_id=plan.resolved_model.provider_model_binding_id,
            )
            intent: ImageGenerationIntent | VideoGenerationIntentV1
            if request.stage == "image_keyframe":
                ref = refs[0] if refs else None
                intent = ImageGenerationIntent.model_validate(
                    {
                        "prompt": plan.prompt,
                        "aspect_ratio": project.aspect_ratio,
                        "selection": selection,
                        "mode_id": plan.mode_id,
                        "reference_artifact_id": ref.artifact_id if ref else None,
                        "reference_fingerprint": ref.fingerprint if ref else None,
                        "reference_mime": ref.mime_type if ref else None,
                    }
                )
            else:
                # The canonical Workbench NodeRun currently freezes five seconds
                # and the project ratio, not arbitrary caller-supplied output controls.
                intent = VideoGenerationIntentV1(
                    prompt=plan.prompt,
                    selection=selection,
                    mode_id=plan.mode_id,
                    references=[
                        ArtifactReferenceIntent(artifact_id=r.artifact_id, role=r.role)
                        for r in refs
                    ],
                    output=VideoOutputIntent.model_validate(
                        {
                            "aspect_ratio": project.aspect_ratio,
                            "duration_seconds": 5,
                            "generate_audio": False,
                        }
                    ),
                )
            if not plan.resolved_model.invoke_model_value:
                raise ValidationAppError("frozen invoke model is missing")
            if plan.resolved_model.native_options:
                raise ValidationAppError(
                    "native options are not supported by this preview contract"
                )
            compilation = await preview_compile(
                manifest=catalog,
                intent=intent,
                references=refs,
                invoke_model_value=plan.resolved_model.invoke_model_value,
            )
            if plan.capability_gaps:
                compilation = compilation.model_copy(
                    update={
                        "readiness": "blocked",
                        "errors": [*compilation.errors, "UNACCEPTED_CAPABILITY_GAP"],
                    }
                )
            report = inspect_manifest(
                to_v3_model_manifest(catalog, transport_profile_id="inspection"),
                catalog=catalog,
            )
            return GenerationCompileRead(
                plan_fingerprint=plan.plan_fingerprint or "",
                snapshot_hash=hash_manifest(
                    {
                        "plan_fingerprint": plan.plan_fingerprint,
                        "compile_hash": compilation.semantic_hash,
                    }
                ),
                model=report,
                compilation=compilation,
                reference_plan=refs,
                observed_versions={"shot": shot.version},
                warnings=["SAVED_CREATIVE_STATE_ONLY", "NO_EXECUTION_AUTHORIZATION"],
            )

    async def get_generation_snapshot(
        self,
        *,
        project_id: UUID,
        shot_id: UUID,
        run_id: UUID,
    ) -> GenerationSnapshotRead:
        await self._project(project_id)
        await self._shot(project_id, shot_id)
        run = await self._session.scalar(
            select(NodeRun).where(
                NodeRun.id == run_id,
                NodeRun.project_id == project_id,
                NodeRun.input_snapshot["shot_id"].as_string() == str(shot_id),
            )
        )
        if run is None:
            raise NotFoundError("generation snapshot not found")
        from app.production.execution_plan import WorkbenchExecutionPlan

        plan: WorkbenchExecutionPlan | None = None
        missing: list[str] = []
        try:
            plan = WorkbenchExecutionPlan.model_validate(run.input_snapshot.get("workbench_plan"))
            if plan.project_id != project_id or plan.shot_id != shot_id:
                plan = None
                missing.append("FROZEN_PLAN_SCOPE_MISMATCH")
        except ValueError:
            missing.append("WORKBENCH_PLAN_UNAVAILABLE")
        operations = list(
            (
                await self._session.scalars(
                    select(ProviderOperation)
                    .where(
                        ProviderOperation.node_run_id == run.id,
                    )
                    .order_by(ProviderOperation.attempt_no, ProviderOperation.id)
                )
            ).all()
        )
        artifact = (
            await self._session.scalar(
                select(Artifact).where(
                    Artifact.id == run.result_artifact_id,
                    Artifact.project_id == project_id,
                )
            )
            if run.result_artifact_id
            else None
        )
        refs: list[PreviewReference] = []
        for ref in plan.planned_references if plan else []:
            try:
                refs.append(
                    PreviewReference.model_validate(
                        {
                            "role": ref.role,
                            "artifact_id": ref.artifact_id,
                            "fingerprint": ref.fingerprint,
                            "mime_type": ref.mime_type,
                        }
                    )
                )
            except ValueError:
                missing.append("FROZEN_REFERENCE_METADATA_INCOMPLETE")
        if not operations:
            missing.append("COMPILED_OPERATION_UNAVAILABLE")
        if artifact is None:
            missing.append("OBSERVED_ARTIFACT_UNAVAILABLE")
        return GenerationSnapshotRead(
            run_id=run.id,
            shot_id=shot_id,
            status=run.status,
            input_hash=run.input_hash,
            plan_fingerprint=plan.plan_fingerprint if plan else None,
            prompt_hash=hashlib.sha256(plan.prompt.encode()).hexdigest() if plan else None,
            requested_model_id=plan.resolved_model.requested_model_id if plan else None,
            planned_model_id=plan.resolved_model.resolved_model_id if plan else None,
            compiled_models=[op.actual_model for op in operations],
            operation_ids=[op.id for op in operations],
            compiled_request_hashes=[op.request_fingerprint for op in operations],
            compiled_options=[_compiled_options(op.request_summary) for op in operations],
            operation_statuses=[op.status for op in operations],
            reference_plan=refs,
            artifact_id=artifact.id if artifact else None,
            artifact_hash=artifact.content_hash if artifact else None,
            observed_output={
                "width": artifact.width,
                "height": artifact.height,
                "duration_seconds": str(artifact.duration_seconds)
                if artifact.duration_seconds is not None
                else None,
                "mime_type": artifact.mime_type,
            }
            if artifact
            else {},
            evidence_missing=sorted(set(missing)),
        )
