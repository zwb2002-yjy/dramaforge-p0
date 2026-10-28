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
from app.providers.catalog_loader import hash_manifest
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.compile_preview import CompilePreview, PreviewReference
from app.providers.litellm_gateway.workspace_registry import workspace_model_registry
from app.providers.manifest import ModelCapabilityManifest, ParameterSpec, to_v3_model_manifest
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.service import default_model_registry
from app.providers.model_profiles.slots import MODEL_SLOT_DEFINITIONS, ModelSlot
from app.providers.model_resolution import ExecutionModelResolution, ExecutionModelResolver
from app.providers.models import ProviderConnection
from app.providers.workbench_contract import (
    implemented_workbench_options,
    select_workbench_contract,
    workbench_ui_mode,
)
from app.shared.errors import NotFoundError, ValidationAppError

Stage = Literal["image_keyframe", "video"]
GenerationOptionBlocker = Literal["compiler_unavailable", "fixed_value", "sensitive", "deprecated"]
_STAGE = {
    "image_keyframe": (ModelSlot.VISUAL_KEYFRAME, Capability.IMAGE_GENERATE, "keyframe"),
    "video": (ModelSlot.VIDEO_SHOT, Capability.VIDEO_IMAGE_TO_VIDEO, "video"),
}


class GenerationOptionRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    parameter: ParameterSpec
    editable: bool
    reason: GenerationOptionBlocker | None = None
    inherited_value: JsonValue | None = None
    inherited_source: str = "contract_default"


class ModelQueryRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    selection: Literal["explicit_catalog", "current_binding", "text_slot"]
    report: ModelCapabilityReport
    binding_id: UUID | None = None
    profile_version: int | None = None
    mode_id: str | None = None
    identity_hash: str | None = None
    resolution: ExecutionModelResolution | None = None
    generation_options: dict[str, GenerationOptionRead] = Field(default_factory=dict)
    connection_label: str | None = None


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

    effective = summary.get("effective_request_redacted")
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

    async def _catalog(self, entry_id: UUID | None) -> tuple[ModelCapabilityManifest, str]:
        entry = await self._session.get(ModelCatalogEntry, entry_id) if entry_id else None
        if entry is None:
            raise NotFoundError("resolved catalog not found")
        if hash_manifest(entry.capability_manifest_json) != entry.contract_manifest_hash:
            raise ValidationAppError("catalog manifest identity mismatch")
        return (
            ModelCapabilityManifest.model_validate(entry.capability_manifest_json),
            entry.contract_manifest_hash,
        )

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
            registry = await workspace_model_registry(
                self._session,
                workspace_id=project.workspace_id,
                base_registry=default_model_registry(),
            )
            report = inspect_catalog_model(model_id, registry=registry)
            result = ModelQueryRead(selection="explicit_catalog", report=report, mode_id=mode_id)
        elif stage is not None:
            model_slot, capability, purpose = _STAGE[stage]
            if stage == "video" and mode_id is not None:
                try:
                    ui_mode = workbench_ui_mode(media_kind="video", mode_id=mode_id)
                except ValueError as exc:
                    raise ValidationAppError("model input mode is not declared") from exc
                capability = {
                    "first_frame": Capability.VIDEO_IMAGE_TO_VIDEO,
                    "text_to_video": Capability.VIDEO_TEXT_TO_VIDEO,
                    "last_frame": Capability.VIDEO_LAST_FRAME_TO_VIDEO,
                    "first_last_frame": Capability.VIDEO_FIRST_LAST_FRAME,
                    "omni_reference": Capability.VIDEO_REFERENCE_TO_VIDEO,
                }[ui_mode]
            resolution = await ExecutionModelResolver(self._session).resolve(
                project=project,
                slot=model_slot,
                capability=capability,
                purpose=purpose,
                mode_id=mode_id,
            )
            if resolution.catalog_entry_id is None:
                raise ValidationAppError(
                    "current model binding unavailable",
                    details={
                        "code": resolution.reason or "MODEL_BINDING_UNAVAILABLE",
                    },
                )
            catalog, catalog_hash = await self._catalog(resolution.catalog_entry_id)
            manifest = to_v3_model_manifest(catalog, transport_profile_id="inspection")
            spec = manifest.capability_specs.get(capability)
            parameters: dict[str, ParameterSpec] = {}
            if spec is not None:
                parameters.update(spec.common_options)
                parameters.update(spec.native_options)
                selected_mode = mode_id
                operation = catalog.operations.get(
                    "video.generate" if stage == "video" else "image.generate"
                )
                if (
                    spec.modes
                    and selected_mode not in spec.modes
                    and operation
                    and operation.input_contracts
                ):
                    roles = {
                        "text_to_image": [],
                        "text_to_video": [],
                        "first_frame": ["first_frame"],
                        "last_frame": ["last_frame"],
                        "first_last_frame": ["first_frame", "last_frame"],
                        "omni_reference": ["reference_image"],
                    }
                    ui_mode = workbench_ui_mode(
                        media_kind=catalog.media_kind,
                        mode_id=mode_id or "explicit_binding",
                    )
                    try:
                        selected_mode = select_workbench_contract(
                            operation=operation,
                            media_kind=catalog.media_kind,
                            ui_mode_id=ui_mode,
                            references=[(role, None) for role in roles[ui_mode]],
                        ).contract_id
                    except ValueError:
                        selected_mode = (
                            None  # Reference-dependent options need actual input preflight.
                        )
                if spec.modes and selected_mode in spec.modes:
                    mode = spec.mode_spec(selected_mode)
                    parameters = {**mode.common_options, **mode.native_options}
                elif spec.modes:
                    parameters = {}
            implemented = implemented_workbench_options(catalog)
            options: dict[str, GenerationOptionRead] = {}
            for name, parameter in parameters.items():
                fixed = parameter.enum is not None and len(parameter.enum) == 1
                reason: GenerationOptionBlocker | None = None
                if parameter.sensitive:
                    reason = "sensitive"
                elif parameter.deprecated:
                    reason = "deprecated"
                elif name not in implemented or resolution.status != "RESOLVED":
                    reason = "compiler_unavailable"
                elif fixed:
                    reason = "fixed_value"
                inherited = parameter.default
                source = "contract_default"
                if name == "aspect_ratio" and inherited is None:
                    inherited, source = project.aspect_ratio, "project"
                elif fixed and inherited is None:
                    inherited = (parameter.enum or [None])[0]
                if resolution.native_options.get(name) is not None:
                    inherited, source = resolution.native_options[name], resolution.source
                options[name] = GenerationOptionRead(
                    parameter=parameter,
                    editable=reason is None,
                    reason=reason,
                    inherited_value=None if parameter.sensitive else inherited,
                    inherited_source=source,
                )
            connection = await self._session.get(
                ProviderConnection, resolution.provider_connection_id
            )
            result = ModelQueryRead(
                selection="current_binding",
                report=inspect_manifest(manifest, catalog=catalog, catalog_hash=catalog_hash),
                binding_id=resolution.provider_model_binding_id,
                mode_id=mode_id,
                identity_hash=hash_manifest(resolution.model_dump(mode="json")),
                resolution=resolution.model_copy(
                    update={
                        "native_options": {
                            name: value
                            for name, value in resolution.native_options.items()
                            if name in parameters and not parameters[name].sensitive
                        }
                    }
                ),
                generation_options=options,
                connection_label=connection.display_name if connection is not None else None,
            )
        else:
            assert slot is not None
            if Capability.TEXT_GENERATE not in MODEL_SLOT_DEFINITIONS[slot].required_capabilities:
                raise ValidationAppError("use stage for a current media binding")
            resolution_text, registry = await ModelBindingResolver(
                self._session
            ).resolve_with_registry(
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
        if mode_id is not None and stage is None:
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
            catalog, catalog_hash = await self._catalog(plan.resolved_model.catalog_entry_id)
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
            compilation = await WorkbenchExecutionService(
                self._session, user_id=self._actor.id
            ).preview_compiler_contract(project=project, plan=plan)
            if compilation is None:
                raise ValidationAppError(
                    "Execution plan cannot produce compiler evidence",
                    details={"code": "COMPILER_PREVIEW_UNAVAILABLE"},
                )
            # Diagnostics expose the same compiler identity/options, while the
            # authorized execution-plan view owns prompt and redacted Wire UI.
            compilation = compilation.model_copy(update={"redacted_wire": {}})
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
                catalog_hash=catalog_hash,
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
