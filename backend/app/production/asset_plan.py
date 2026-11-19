"""Read-only asset image execution plan (I8a-03).

The plan binds the asset target, the project image binding, the model's declared
image.generate contract, the compiled prompt and the explicit references. It writes
nothing: no Graph, no NodeRun and no Provider call. Asset commands reuse the same
ProductionCommands/Worker path as shot commands; this module only previews.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.models import Asset, AssetVersionReference
from app.production.execution_plan import fingerprint_plan
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.manifest import (
    ModelCapabilityManifest,
    OperationManifest,
    read_catalog_manifest,
)
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.models import ProviderModelBinding
from app.providers.reference_roles import canonical_reference_role
from app.providers.validator import validate_parameter
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class AssetCreativeRequirementChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["appearance", "environment", "visual_style"]
    description: str = Field(min_length=1, max_length=2000)


class AssetCreativeRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    summary: str = Field(min_length=1, max_length=16000)
    appearance: str | None = Field(default=None, max_length=8000)
    environment: str | None = Field(default=None, max_length=8000)
    visual_style: str | None = Field(default=None, max_length=8000)
    proposed_changes: list[AssetCreativeRequirementChange] = Field(
        default_factory=list, max_length=20
    )


class AssetImageReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["asset_reference"] = "asset_reference"
    asset_version_reference_id: UUID
    role: str = Field(min_length=1, max_length=80)


class AssetImagePlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_asset_version: int = Field(ge=1)
    operation: Literal["image_generate", "image_edit"]
    mode_id: str = Field(min_length=1, max_length=120)
    requirements: AssetCreativeRequirements
    prompt_override: str | None = Field(default=None, min_length=1, max_length=20000)
    base_asset_version_id: UUID | None = None
    requested_binding_id: UUID | None = None
    references: list[AssetImageReference] = Field(default_factory=list)
    source_context_refs: list[dict[str, JsonValue]] = Field(default_factory=list)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    output_count: int = Field(default=1, ge=1, le=8)


class AssetExecutionBody(AssetImagePlanBody):
    """One explicit asset command: the previewed plan plus its frozen fingerprint."""

    plan_fingerprint: str = Field(min_length=64, max_length=64)


class AssetPlanTarget(BaseModel):
    kind: Literal["asset"] = "asset"
    asset_id: UUID
    asset_version: int


class AssetPlannedReference(BaseModel):
    asset_version_reference_id: UUID
    asset_version_id: UUID
    artifact_id: UUID
    role: str


class AssetExecutionPlanRead(BaseModel):
    target: AssetPlanTarget
    stage: Literal["asset_image"] = "asset_image"
    plan_fingerprint: str
    # Frozen model identity the command freezes into the NodeRun snapshot.
    resolution: dict[str, JsonValue] = Field(default_factory=dict)
    binding_id: UUID
    model_id: str
    provider_type: str
    capability: str
    prompt: str
    parameters: dict[str, JsonValue]
    output_count: int
    references: list[AssetPlannedReference]
    max_provider_operations: int
    notices: list[str] = Field(default_factory=list)


def _compile_prompt(requirements: AssetCreativeRequirements, override: str | None) -> str:
    if override is not None:
        return override
    parts = [requirements.summary.strip()]
    for label, value in (
        ("外观", requirements.appearance),
        ("环境", requirements.environment),
        ("视觉风格", requirements.visual_style),
    ):
        if value and value.strip():
            parts.append(f"{label}：{value.strip()}")
    if requirements.proposed_changes:
        changes = "；".join(
            f"{change.field}：{change.description.strip()}"
            for change in requirements.proposed_changes
        )
        parts.append(f"本次调整：{changes}")
    return "\n".join(part for part in parts if part)


async def _resolve_image_binding(
    session: AsyncSession, *, project: Project, requested_binding_id: UUID | None
) -> tuple[ProviderModelBinding, ModelCatalogEntry, OperationManifest]:
    profile = await ProductionModelProfileService(session).get_effective_for_project(
        project=project
    )
    binding_id = requested_binding_id or (
        profile.image_model_binding_id if profile is not None else None
    )
    if binding_id is None:
        raise ValidationAppError(
            "项目未配置图片模型；请在项目设置中选择后再预览。",
            details={"code": "ASSET_IMAGE_BINDING_MISSING"},
        )
    binding = await session.get(ProviderModelBinding, binding_id)
    if binding is None or binding.workspace_id != project.workspace_id:
        raise NotFoundError("Image binding not found")
    if not binding.enabled:
        raise ValidationAppError(
            "已保存的图片模型当前不可用；不会自动切换到其他模型。",
            details={"code": "ASSET_IMAGE_BINDING_DISABLED"},
        )
    if binding.media_type != "image":
        raise ValidationAppError(
            "所选模型不是图片模型。",
            details={"code": "ASSET_IMAGE_BINDING_KIND"},
        )
    entry = (
        await session.get(ModelCatalogEntry, binding.catalog_entry_id)
        if binding.catalog_entry_id is not None
        else None
    )
    if entry is None or entry.media_kind != "image":
        raise ValidationAppError(
            "图片模型目录不可用。",
            details={"code": "ASSET_IMAGE_CATALOG_MISSING"},
        )
    manifest = read_catalog_manifest(entry.capability_manifest_json)
    if not isinstance(manifest, ModelCapabilityManifest):
        raise ValidationAppError(
            "该模型的V2清单尚未接入资产计划。",
            details={"code": "ASSET_MANIFEST_V2_NOT_WIRED"},
        )
    operation = manifest.operations.get("image.generate")
    if operation is None:
        raise ValidationAppError(
            "该模型未声明图片生成能力。",
            details={"code": "ASSET_CAPABILITY_UNSUPPORTED"},
        )
    return binding, entry, operation


def _validate_parameters(
    operation: OperationManifest, parameters: dict[str, JsonValue]
) -> None:
    for key, value in parameters.items():
        spec = operation.output_options.get(key)
        if spec is None:
            raise ValidationAppError(
                "参数不在该模型的图片合同内。",
                details={"code": "ASSET_PARAMETER_UNKNOWN", "parameter": key},
            )
        validate_parameter(key, value, spec)


async def _resolve_references(
    session: AsyncSession,
    *,
    project: Project,
    body: AssetImagePlanBody,
    operation: OperationManifest,
) -> list[AssetPlannedReference]:
    planned: list[AssetPlannedReference] = []
    for reference in body.references:
        row = await session.scalar(
            select(AssetVersionReference).where(
                AssetVersionReference.id == reference.asset_version_reference_id,
                AssetVersionReference.project_id == project.id,
            )
        )
        if row is None:
            raise NotFoundError("Asset version reference not found")
        role = canonical_reference_role(reference.role) or reference.role
        if role not in operation.reference_constraints:
            raise ValidationAppError(
                "该模型不支持此参考角色。",
                details={"code": "ASSET_REFERENCE_ROLE_UNSUPPORTED", "role": role},
            )
        planned.append(
            AssetPlannedReference(
                asset_version_reference_id=row.id,
                asset_version_id=row.asset_version_id,
                artifact_id=row.artifact_id,
                role=role,
            )
        )
    return planned


async def build_asset_image_plan(
    session: AsyncSession,
    *,
    project: Project,
    asset_id: UUID,
    body: AssetImagePlanBody,
) -> AssetExecutionPlanRead:
    """Build the read-only plan; no Graph/NodeRun/Provider side effects."""
    asset = await session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.project_id == project.id)
    )
    if asset is None:
        raise NotFoundError("Asset not found")
    if body.expected_asset_version != asset.version:
        raise ConflictError(
            "asset version changed; review the current plan",
            details={"code": "ASSET_VERSION_CONFLICT", "current": asset.version},
        )
    if body.operation == "image_edit":
        raise ValidationAppError(
            "资产图片编辑尚未接线；请先用 image_generate。",
            details={"code": "ASSET_EDIT_NOT_WIRED"},
        )
    if body.base_asset_version_id is not None:
        raise ValidationAppError(
            "image_generate does not accept a base version.",
            details={"code": "ASSET_BASE_VERSION_NOT_ALLOWED"},
        )
    binding, entry, operation = await _resolve_image_binding(
        session, project=project, requested_binding_id=body.requested_binding_id
    )
    from app.providers.capabilities import Capability
    from app.providers.model_profiles.slots import ModelSlot
    from app.providers.model_resolution import ExecutionModelResolver

    resolution = await ExecutionModelResolver(session).resolve(
        project=project,
        slot=ModelSlot.VISUAL_KEYFRAME,
        capability=Capability.IMAGE_GENERATE,
        purpose="keyframe",
        mode_id=body.mode_id,
        requested_binding_id=binding.id,
    )
    from sqlalchemy import select as _select

    from app.providers.models import ProviderConnectionRevision

    revision = await session.scalar(
        _select(ProviderConnectionRevision)
        .where(ProviderConnectionRevision.connection_id == binding.connection_id)
        .order_by(ProviderConnectionRevision.revision_no.desc())
        .limit(1)
    )
    if revision is None:
        raise ValidationAppError(
            "图片模型连接缺少不可变修订。",
            details={"code": "ASSET_CONNECTION_REVISION_UNAVAILABLE"},
        )
    resolution = resolution.model_copy(
        update={
            "provider_connection_revision_id": revision.id,
            "credential_revision_id": revision.credential_revision_id,
        }
    )
    _validate_parameters(operation, body.parameters)
    max_outputs = operation.output_constraints.get("max_outputs")
    if isinstance(max_outputs, int) and body.output_count > max_outputs:
        raise ValidationAppError(
            "output_count exceeds the model contract.",
            details={
                "code": "ASSET_OUTPUT_COUNT_UNSUPPORTED",
                "max_outputs": max_outputs,
            },
        )
    references = await _resolve_references(
        session, project=project, body=body, operation=operation
    )
    prompt = _compile_prompt(body.requirements, body.prompt_override)
    payload = {
        "target": {
            "kind": "asset",
            "asset_id": str(asset.id),
            "asset_version": asset.version,
        },
        "stage": "asset_image",
        "binding_id": str(binding.id),
        "catalog_entry_id": str(entry.id),
        "operation": body.operation,
        "mode_id": body.mode_id,
        "prompt": prompt,
        "parameters": body.parameters,
        "output_count": body.output_count,
        "references": [item.model_dump(mode="json") for item in references],
        "source_context_refs": body.source_context_refs,
    }
    fingerprint = fingerprint_plan(payload)
    notices: list[str] = []
    if body.prompt_override is not None:
        notices.append("已使用高级提示词覆盖；普通用户可留空由服务编译。")
    return AssetExecutionPlanRead(
        target=AssetPlanTarget(
            asset_id=asset.id, asset_version=asset.version
        ),
        plan_fingerprint=fingerprint,
        resolution=resolution.model_dump(mode="json"),
        binding_id=binding.id,
        model_id=binding.model_id,
        provider_type=entry.provider_type,
        capability="image.generate",
        prompt=prompt,
        parameters=body.parameters,
        output_count=body.output_count,
        references=references,
        max_provider_operations=1,
        notices=notices,
    )


def plan_payload_digest(plan: AssetExecutionPlanRead) -> str:
    """Stable digest used by tests and later command binding."""
    return hashlib.sha256(
        json.dumps(plan.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


__all__ = [
    "AssetCreativeRequirements",
    "AssetExecutionPlanRead",
    "AssetImagePlanBody",
    "AssetImageReference",
    "AssetPlanTarget",
    "AssetPlannedReference",
    "build_asset_image_plan",
    "plan_payload_digest",
]
