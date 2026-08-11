"""Unified Generation API (V3 spec §58).

Read surface (capabilities / models / model manifest) comes from the V3 model
registry; generation creation is NodeRun-backed through the existing engine
(see :mod:`app.providers.generation_service`). Routes are project-scoped per the
repo convention (mirrors ``model-candidates`` / ``characters``). The API never
exposes provider headers, base URLs, raw payloads or credentials (spec §24/§64).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SelectedWorkspace, SessionDep, require_selected_workspace
from app.providers.bootstrap import default_v3_registry
from app.providers.capabilities import Capability
from app.providers.generation_service import GenerationService
from app.providers.manifest import ModelManifest
from app.providers.models import ProviderConnection
from app.providers.registry import ModelRegistry
from app.providers.router import CapabilityRouter
from app.shared.errors import NotFoundError, ValidationAppError

router = APIRouter(tags=["generations"])

_MODEL_REGISTRY, _TRANSPORT_REGISTRY = default_v3_registry()


class CapabilityRead(BaseModel):
    id: str
    display_name: str


class ModelRead(BaseModel):
    id: str
    provider_id: str
    display_name: str
    enabled: bool
    configured: bool
    available: bool
    capabilities: list[str]


class ManifestRead(BaseModel):
    id: str
    provider_id: str
    model_name: str
    display_name: str
    execution_mode: str
    supports_cancel: bool
    capability_specs: dict[str, Any]


class GenerationCreateBody(BaseModel):
    capability: str = Field(min_length=1)
    model_id: str | None = None
    slot: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    native_options: dict[str, Any] = Field(default_factory=dict)


class GenerationCreateResponse(BaseModel):
    operation_id: UUID
    status: str
    requested_capability: str
    requested_model: str | None


class ProviderOperationRead(BaseModel):
    provider_operation_id: UUID | None
    provider: str | None
    model: str | None
    remote_task_id: str | None


class GenerationOperationRead(BaseModel):
    operation_id: UUID
    status: str
    requested_capability: str
    requested_model: str | None
    error_code: str | None
    result_artifact_id: UUID | None
    provider_operation: ProviderOperationRead


_CAPABILITY_DISPLAY_NAMES: dict[Capability, str] = {
    Capability.TEXT_GENERATE: "文本生成",
    Capability.IMAGE_GENERATE: "文生图 / 图生图",
    Capability.IMAGE_EDIT: "图片编辑",
    Capability.VIDEO_TEXT_TO_VIDEO: "文生视频",
    Capability.VIDEO_IMAGE_TO_VIDEO: "图生视频",
    Capability.VIDEO_FIRST_LAST_FRAME: "首尾帧视频",
    Capability.VIDEO_REFERENCE_TO_VIDEO: "多参考视频",
    Capability.AUDIO_TTS: "语音合成",
}


def _registry() -> ModelRegistry:
    return _MODEL_REGISTRY


@router.get(
    "/capabilities",
    response_model=list[CapabilityRead],
    dependencies=[Depends(require_selected_workspace)],
)
async def list_capabilities() -> list[CapabilityRead]:
    return [
        CapabilityRead(
            id=str(capability),
            display_name=_CAPABILITY_DISPLAY_NAMES.get(capability, str(capability)),
        )
        for capability in Capability
    ]


@router.get(
    "/models",
    response_model=list[ModelRead],
    dependencies=[Depends(require_selected_workspace)],
)
async def list_models(
    capability: str | None = None,
    workspace: SelectedWorkspace = None,  # type: ignore[assignment]
    session: SessionDep = None,  # type: ignore[assignment]
) -> list[ModelRead]:
    registry = _registry()
    if capability is not None:
        try:
            selected = registry.find_by_capability(Capability(capability))
        except ValueError as exc:
            raise ValidationAppError(
                f"unknown capability: {capability}",
                details={"code": "UNKNOWN_CAPABILITY"},
            ) from exc
    else:
        selected = registry.list_models()
    configured: set[str] = set()
    if session is not None and workspace is not None:
        rows = list(
            (
                await session.execute(
                    select(ProviderConnection).where(
                        ProviderConnection.workspace_id == workspace.id,
                        ProviderConnection.enabled.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        configured = {row.provider_type for row in rows}
    return [
        ModelRead(
            id=model.manifest.id,
            provider_id=model.manifest.provider_id,
            display_name=model.manifest.display_name,
            enabled=True,
            configured=model.manifest.provider_id in configured,
            available=model.manifest.provider_id in configured,
            capabilities=sorted(str(cap) for cap in model.manifest.capability_specs),
        )
        for model in selected
    ]


@router.get(
    "/models/{model_id:path}",
    response_model=ManifestRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def get_model_manifest(model_id: str) -> ManifestRead:
    model = _registry().get_or_none(model_id)
    if model is None:
        raise NotFoundError("model not found")
    manifest: ModelManifest = model.manifest
    return ManifestRead(
        id=manifest.id,
        provider_id=manifest.provider_id,
        model_name=manifest.model_name,
        display_name=manifest.display_name,
        execution_mode=str(manifest.execution_mode),
        supports_cancel=manifest.supports_cancel,
        capability_specs={
            str(capability): spec.model_dump(mode="json")
            for capability, spec in manifest.capability_specs.items()
        },
    )


@router.post(
    "/projects/{project_id}/generations",
    response_model=GenerationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_selected_workspace)],
)
async def create_generation(
    project_id: UUID,
    body: GenerationCreateBody,
    user: CurrentUser,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> GenerationCreateResponse:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    try:
        capability = Capability(body.capability)
    except ValueError as exc:
        raise ValidationAppError(
            f"unknown capability: {body.capability}",
            details={"code": "UNKNOWN_CAPABILITY"},
        ) from exc
    service = GenerationService(session, CapabilityRouter(registry=_registry()))
    run = await service.create_generation(
        project=project,
        actor=user,
        capability=capability,
        model_id=body.model_id,
        slot=body.slot,
        input_data=body.input,
        options=body.options,
        native_options=body.native_options,
        idempotency_key=idempotency_key,
    )
    await service.enqueue(run)
    await session.commit()
    snapshot = dict(run.input_snapshot or {})
    generation = snapshot.get("generation") or {}
    resolved_model = None
    if isinstance(generation, dict):
        resolved_model = (
            str(generation["requested_model"]) if generation.get("requested_model") else None
        )
    return GenerationCreateResponse(
        operation_id=run.id,
        status=run.status,
        requested_capability=body.capability,
        requested_model=resolved_model,
    )


@router.get(
    "/projects/{project_id}/generations/{operation_id}",
    response_model=GenerationOperationRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def get_generation(
    project_id: UUID,
    operation_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> GenerationOperationRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    service = GenerationService(session, CapabilityRouter(registry=_registry()))
    run = await service.get_generation(project=project, operation_id=operation_id)
    return await _read_operation(session, run)


@router.post(
    "/projects/{project_id}/generations/{operation_id}/cancel",
    response_model=GenerationOperationRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def cancel_generation(
    project_id: UUID,
    operation_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> GenerationOperationRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    service = GenerationService(session, CapabilityRouter(registry=_registry()))
    run = await service.cancel_generation(project=project, operation_id=operation_id)
    await session.commit()
    return await _read_operation(session, run)


async def _read_operation(session: Any, run: Any) -> GenerationOperationRead:
    from app.execution.models import ProviderOperation

    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    snapshot = dict(run.input_snapshot or {})
    generation = snapshot.get("generation") or {}
    requested_capability = (
        str(generation.get("capability") or "") if isinstance(generation, dict) else ""
    )
    requested_model = None
    if isinstance(generation, dict):
        requested_model = (
            str(generation["requested_model"]) if generation.get("requested_model") else None
        )
    provider_op = ProviderOperationRead(
        provider_operation_id=op.id if op is not None else None,
        provider=op.actual_provider if op is not None else None,
        model=op.actual_model if op is not None else None,
        remote_task_id=op.provider_operation_id if op is not None else None,
    )
    return GenerationOperationRead(
        operation_id=run.id,
        status=run.status,
        requested_capability=requested_capability,
        requested_model=requested_model,
        error_code=run.error_code,
        result_artifact_id=run.result_artifact_id,
        provider_operation=provider_op,
    )
