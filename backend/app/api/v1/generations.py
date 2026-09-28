"""Read-only Generation catalog API (V3 spec §58).

Capabilities / models / model manifest come from the V3 model registry. Media
generation has exactly one product writer — the workbench execution path
(execution-plan -> executions -> NodeRun) — so this module deliberately has no
create/get/cancel product surface. The API never exposes provider headers, base
URLs, raw payloads or credentials (spec §24/§64).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import (
    SelectedWorkspace,
    SessionDep,
    SettingsDep,
    require_selected_workspace,
)
from app.providers.bootstrap import default_v3_registry
from app.providers.capabilities import Capability
from app.providers.manifest import ModelManifest
from app.providers.models import ProviderConnection
from app.providers.registry import ModelRegistry
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
    settings: SettingsDep = None,  # type: ignore[assignment]
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
    # The LiteLLM gateway is process-level configuration, not a workspace
    # ProviderConnection. Keep this read surface aligned with ModelProfile reads.
    litellm_configured = bool(
        settings is not None
        and settings.litellm_gateway_url.strip()
        and settings.litellm_api_key.strip()
    )
    return [
        ModelRead(
            id=model.manifest.id,
            provider_id=model.manifest.provider_id,
            display_name=model.manifest.display_name,
            enabled=True,
            configured=(
                litellm_configured
                if model.manifest.provider_id == "litellm"
                else model.manifest.provider_id in configured
            ),
            available=(
                litellm_configured
                if model.manifest.provider_id == "litellm"
                else model.manifest.provider_id in configured
            ),
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
