"""Workspace Provider Connection, capability Probe, and binding API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, SecretStr

from app.access.projects import ProjectService
from app.api.deps import (
    CsrfDep,
    CurrentUser,
    SelectedWorkspace,
    SessionDep,
    require_selected_workspace,
)
from app.providers.catalog_service import ModelCatalogService
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import (
    ProviderCapabilityEvidence,
    ProviderConnection,
    ProviderModelBinding,
    ProviderQualityEvidence,
)
from app.providers.registry import list_plugins
from app.shared.errors import NotFoundError

router = APIRouter(tags=["provider-connections"])


class ProviderPluginModelRead(BaseModel):
    model_id: str
    display_name: str
    media_type: str
    model_revision: str
    lifecycle: str
    catalog_source: str
    capabilities: list[str]
    option_schema: dict[str, object]


class ProviderPluginRead(BaseModel):
    provider_type: str
    protocol_profile: str
    display_name: str
    default_base_url: str
    implemented: bool
    paid_capabilities: list[str]
    capabilities: list[str]
    model_list_path: str
    models: list[ProviderPluginModelRead]


@router.get("/provider-plugins", response_model=list[ProviderPluginRead])
async def list_provider_plugins(session: SessionDep) -> list[ProviderPluginRead]:
    """Return the installed plugin contracts and catalog models.

    This is deliberately metadata-only: credentials and workspace connections
    remain private. The frontend uses this response to render provider setup,
    capability probes, and model binding choices without hard-coded supplier
    names or model ids.
    """
    entries = await ModelCatalogService(session).list_entries(lifecycle="active")
    by_plugin: dict[tuple[str, str], list[ProviderPluginModelRead]] = {}
    for entry in entries:
        operations = entry.capability_manifest_json.get("operations") or {}
        capabilities = sorted(
            {
                str(capability)
                for operation in operations.values()
                if isinstance(operation, dict)
                for capability in (operation.get("capabilities") or [])
            }
        )
        by_plugin.setdefault((entry.provider_type, entry.protocol_profile), []).append(
            ProviderPluginModelRead(
                model_id=entry.model_id,
                display_name=entry.display_name,
                media_type=entry.media_kind,
                model_revision=entry.model_revision,
                lifecycle=entry.lifecycle,
                catalog_source=entry.catalog_source,
                capabilities=capabilities,
                option_schema=dict(entry.option_schema_json or {}),
            )
        )
    result: list[ProviderPluginRead] = []
    for plugin in list_plugins():
        models = by_plugin.get((plugin.provider_type, plugin.protocol_profile), [])
        result.append(
            ProviderPluginRead(
                provider_type=plugin.provider_type,
                protocol_profile=plugin.protocol_profile,
                display_name=plugin.display_name,
                default_base_url=plugin.default_base_url,
                implemented=plugin.implemented,
                paid_capabilities=sorted(plugin.paid_capabilities),
                capabilities=sorted(
                    set(plugin.capability_purposes)
                    | set(plugin.paid_capabilities)
                    | {"auth_models"}
                ),
                model_list_path=plugin.model_list_path,
                models=models,
            )
        )
    return result


class ConnectionCreate(BaseModel):
    provider_type: str = Field(default="agnes", min_length=1, max_length=40)
    display_name: str = Field(default="", max_length=120)
    protocol_profile: str = Field(default="agnes_cn_v1", min_length=1, max_length=80)
    base_url: str | None = Field(default=None, max_length=240)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    enabled: bool = True


class ConnectionPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=240)
    enabled: bool | None = None


class CredentialWrite(BaseModel):
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class ConnectionRead(BaseModel):
    id: UUID
    workspace_id: UUID
    provider_type: str
    display_name: str
    base_url: str
    protocol_profile: str
    enabled: bool
    credential_configured: bool
    credential_key_version: str | None
    verification_status: str
    verified_at: datetime | None


class ProbeRequest(BaseModel):
    capability: Literal[
        "auth_models",
        "image_t2i",
        "image_i2i",
        "video_i2v",
        "video_poll_download",
    ]
    model_binding_id: UUID | None = None
    reference_artifact_id: UUID | None = None
    remote_task_id: str | None = None
    remote_query_kind: Literal["video_id", "task_id"] | None = None
    budget_authorized: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=6)


class ProbeRead(BaseModel):
    probe_id: UUID
    capability: str
    status: str
    evidence_level: str
    http_status: int | None
    provider_request_id: str | None
    reference_artifact_id: UUID | None
    model_binding_id: UUID | None
    remote_query_kind: str | None
    request_fingerprint: str
    budget_authorized: Decimal
    provider_cost: Decimal | None
    currency: str
    cost_status: str
    tested_at: datetime
    error_code: str | None


class ModelBindingCreate(BaseModel):
    media_type: Literal["image", "video"]
    model_id: str = Field(min_length=1, max_length=160)
    purpose: Literal["keyframe", "video"]
    enabled: bool = True


class ModelBindingRead(BaseModel):
    id: UUID
    connection_id: UUID
    media_type: str
    model_id: str
    purpose: str
    enabled: bool
    documented: bool
    contract_tested: bool
    account_verified: bool
    quality_gated: bool
    catalog_entry_id: UUID | None
    capability_manifest_hash: str | None
    remote_resource_kind: str | None
    remote_resource_id: str | None
    invoke_model_value: str | None
    pricing_snapshot: dict[str, object]


class BindingPricingWrite(BaseModel):
    unit_amount: Decimal = Field(ge=0, decimal_places=6)
    currency: str = Field(min_length=3, max_length=3)
    billing_unit: str = Field(min_length=1, max_length=80)
    source_note: str = Field(min_length=1, max_length=500)
    owner_verified: Literal[True]


class ProjectBindingWrite(BaseModel):
    model_binding_id: UUID
    selection_strategy: Literal["explicit_binding"] = "explicit_binding"
    fallback_policy: Literal["none"] = "none"


class ProjectBindingRead(BaseModel):
    id: UUID
    project_id: UUID
    purpose: str
    model_binding_id: UUID
    selection_strategy: str
    fallback_policy: str


class QualityEvidenceWrite(BaseModel):
    node_run_id: UUID
    artifact_id: UUID


class QualityEvidenceRead(BaseModel):
    id: UUID
    model_binding_id: UUID
    node_run_id: UUID
    artifact_id: UUID
    evidence_kind: str
    policy_id: str
    score: Decimal | None
    approved_by: UUID
    created_at: datetime


async def _connection_read(
    service: ProviderConnectionService, connection: ProviderConnection
) -> ConnectionRead:
    return ConnectionRead(
        id=connection.id,
        workspace_id=connection.workspace_id,
        provider_type=connection.provider_type,
        display_name=connection.display_name,
        base_url=connection.base_url,
        protocol_profile=connection.protocol_profile,
        enabled=connection.enabled,
        credential_configured=True,
        credential_key_version=await service.credential_version(connection),
        verification_status=connection.verification_status,
        verified_at=connection.verified_at,
    )


def _probe_read(evidence: ProviderCapabilityEvidence) -> ProbeRead:
    return ProbeRead(
        probe_id=evidence.id,
        capability=evidence.capability,
        status=evidence.status,
        evidence_level=evidence.evidence_level,
        http_status=evidence.http_status,
        provider_request_id=evidence.provider_request_id,
        reference_artifact_id=evidence.reference_artifact_id,
        model_binding_id=evidence.model_binding_id,
        remote_query_kind=evidence.remote_query_kind,
        request_fingerprint=evidence.request_fingerprint,
        budget_authorized=evidence.budget_authorized,
        provider_cost=evidence.provider_cost,
        currency=evidence.currency,
        cost_status=evidence.cost_status,
        tested_at=evidence.tested_at,
        error_code=evidence.error_code,
    )


def _model_read(binding: ProviderModelBinding) -> ModelBindingRead:
    return ModelBindingRead(
        id=binding.id,
        connection_id=binding.connection_id,
        media_type=binding.media_type,
        model_id=binding.model_id,
        purpose=binding.purpose,
        enabled=binding.enabled,
        documented=binding.documented,
        contract_tested=binding.contract_tested,
        account_verified=binding.account_verified,
        quality_gated=binding.quality_gated,
        catalog_entry_id=binding.catalog_entry_id,
        capability_manifest_hash=binding.capability_manifest_hash,
        remote_resource_kind=binding.remote_resource_kind,
        remote_resource_id=binding.remote_resource_id,
        invoke_model_value=binding.invoke_model_value,
        pricing_snapshot=dict(binding.pricing_snapshot_json or {}),
    )


def _quality_read(evidence: ProviderQualityEvidence) -> QualityEvidenceRead:
    return QualityEvidenceRead(
        id=evidence.id,
        model_binding_id=evidence.model_binding_id,
        node_run_id=evidence.node_run_id,
        artifact_id=evidence.artifact_id,
        evidence_kind=evidence.evidence_kind,
        policy_id=evidence.policy_id,
        score=evidence.score,
        approved_by=evidence.approved_by,
        created_at=evidence.created_at,
    )


@router.post(
    "/workspaces/{workspace_id}/provider-connections",
    response_model=ConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    workspace_id: UUID,
    body: ConnectionCreate,
    workspace: SelectedWorkspace,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ConnectionRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace_id,
        actor=user,
        display_name=body.display_name,
        api_key=body.api_key.get_secret_value(),
        enabled=body.enabled,
        provider_type=body.provider_type,
        protocol_profile=body.protocol_profile,
        base_url=body.base_url,
    )
    await session.commit()
    return await _connection_read(service, connection)


@router.get(
    "/workspaces/{workspace_id}/provider-connections",
    response_model=list[ConnectionRead],
)
async def list_connections(
    workspace_id: UUID,
    workspace: SelectedWorkspace,
    session: SessionDep,
) -> list[ConnectionRead]:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    service = ProviderConnectionService(session)
    return [
        await _connection_read(service, connection)
        for connection in await service.list_connections(workspace_id=workspace_id)
    ]


@router.get(
    "/workspaces/{workspace_id}/provider-connections/{connection_id}",
    response_model=ConnectionRead,
)
async def get_connection(
    workspace_id: UUID,
    connection_id: UUID,
    workspace: SelectedWorkspace,
    session: SessionDep,
) -> ConnectionRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    service = ProviderConnectionService(session)
    return await _connection_read(
        service,
        await service.get_connection(workspace_id=workspace_id, connection_id=connection_id),
    )


@router.patch(
    "/workspaces/{workspace_id}/provider-connections/{connection_id}",
    response_model=ConnectionRead,
)
async def patch_connection(
    workspace_id: UUID,
    connection_id: UUID,
    body: ConnectionPatch,
    workspace: SelectedWorkspace,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ConnectionRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    service = ProviderConnectionService(session)
    connection = await service.update_connection(
        workspace_id=workspace_id,
        connection_id=connection_id,
        actor=user,
        display_name=body.display_name,
        enabled=body.enabled,
        base_url=body.base_url,
    )
    await session.commit()
    return await _connection_read(service, connection)


@router.put(
    "/workspaces/{workspace_id}/provider-connections/{connection_id}/credential",
    response_model=ConnectionRead,
)
async def put_connection_credential(
    workspace_id: UUID,
    connection_id: UUID,
    body: CredentialWrite,
    workspace: SelectedWorkspace,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ConnectionRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    service = ProviderConnectionService(session)
    connection = await service.update_credential(
        workspace_id=workspace_id,
        connection_id=connection_id,
        actor=user,
        api_key=body.api_key.get_secret_value(),
    )
    await session.commit()
    return await _connection_read(service, connection)


@router.post(
    "/workspaces/{workspace_id}/provider-connections/{connection_id}/probes",
    response_model=ProbeRead,
)
async def run_probe(
    workspace_id: UUID,
    connection_id: UUID,
    body: ProbeRequest,
    workspace: SelectedWorkspace,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProbeRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    evidence = await ProviderConnectionService(session).probe(
        workspace_id=workspace_id,
        connection_id=connection_id,
        actor=user,
        capability=body.capability,
        model_binding_id=body.model_binding_id,
        reference_artifact_id=body.reference_artifact_id,
        remote_task_id=body.remote_task_id,
        remote_query_kind=body.remote_query_kind,
        budget_authorized=body.budget_authorized,
    )
    await session.commit()
    return _probe_read(evidence)


@router.get(
    "/workspaces/{workspace_id}/provider-connections/{connection_id}/probes",
    response_model=list[ProbeRead],
)
async def list_probes(
    workspace_id: UUID,
    connection_id: UUID,
    workspace: SelectedWorkspace,
    session: SessionDep,
) -> list[ProbeRead]:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    evidence = await ProviderConnectionService(session).list_capability_evidence(
        workspace_id=workspace_id,
        connection_id=connection_id,
    )
    return [_probe_read(item) for item in evidence]


@router.post(
    "/workspaces/{workspace_id}/provider-connections/{connection_id}/model-bindings",
    response_model=ModelBindingRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_model_binding(
    workspace_id: UUID,
    connection_id: UUID,
    body: ModelBindingCreate,
    workspace: SelectedWorkspace,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ModelBindingRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    binding = await ProviderConnectionService(session).create_model_binding(
        workspace_id=workspace_id,
        connection_id=connection_id,
        actor=user,
        media_type=body.media_type,
        model_id=body.model_id,
        purpose=body.purpose,
        enabled=body.enabled,
    )
    await session.commit()
    return _model_read(binding)


@router.get(
    "/workspaces/{workspace_id}/provider-connections/{connection_id}/model-bindings",
    response_model=list[ModelBindingRead],
)
async def list_model_bindings(
    workspace_id: UUID,
    connection_id: UUID,
    workspace: SelectedWorkspace,
    session: SessionDep,
) -> list[ModelBindingRead]:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    bindings = await ProviderConnectionService(session).list_model_bindings(
        workspace_id=workspace_id, connection_id=connection_id
    )
    return [_model_read(binding) for binding in bindings]


@router.put(
    (
        "/workspaces/{workspace_id}/provider-connections/{connection_id}"
        "/model-bindings/{model_binding_id}/pricing"
    ),
    response_model=ModelBindingRead,
)
async def set_model_binding_pricing(
    workspace_id: UUID,
    connection_id: UUID,
    model_binding_id: UUID,
    body: BindingPricingWrite,
    workspace: SelectedWorkspace,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ModelBindingRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    binding = await ProviderConnectionService(session).set_binding_pricing(
        workspace_id=workspace_id,
        connection_id=connection_id,
        model_binding_id=model_binding_id,
        actor=user,
        unit_amount=body.unit_amount,
        currency=body.currency,
        billing_unit=body.billing_unit,
        source_note=body.source_note,
    )
    await session.commit()
    return _model_read(binding)


@router.post(
    (
        "/workspaces/{workspace_id}/provider-connections/{connection_id}"
        "/model-bindings/{model_binding_id}/quality-evidence"
    ),
    response_model=QualityEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
async def record_quality_evidence(
    workspace_id: UUID,
    connection_id: UUID,
    model_binding_id: UUID,
    body: QualityEvidenceWrite,
    workspace: SelectedWorkspace,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> QualityEvidenceRead:
    if workspace.id != workspace_id:
        raise NotFoundError("workspace not found")
    evidence = await ProviderConnectionService(session).record_quality_evidence(
        workspace_id=workspace_id,
        connection_id=connection_id,
        model_binding_id=model_binding_id,
        node_run_id=body.node_run_id,
        artifact_id=body.artifact_id,
        actor=user,
    )
    await session.commit()
    return _quality_read(evidence)


@router.put(
    "/projects/{project_id}/provider-bindings/{purpose}",
    response_model=ProjectBindingRead,
    dependencies=[Depends(require_selected_workspace)],
)
async def put_project_binding(
    project_id: UUID,
    purpose: str,
    body: ProjectBindingWrite,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProjectBindingRead:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    binding = await ProviderConnectionService(session).bind_project(
        project=project,
        purpose=purpose,
        model_binding_id=body.model_binding_id,
        fallback_policy=body.fallback_policy,
        actor=user,
        selection_strategy=body.selection_strategy,
    )
    await session.commit()
    return ProjectBindingRead(
        id=binding.id,
        project_id=binding.project_id,
        purpose=binding.purpose,
        model_binding_id=binding.model_binding_id,
        selection_strategy=binding.selection_strategy,
        fallback_policy=binding.fallback_policy,
    )
