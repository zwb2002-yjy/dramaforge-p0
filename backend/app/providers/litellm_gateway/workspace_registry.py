"""Workspace-scoped text model capability plugins from persisted discovery."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.catalog_loader import hash_manifest
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.models import (
    ProviderCapabilityEvidence,
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)
from app.providers.registry import ModelRegistry
from app.providers.workspace_credentials import runtime_text_gateway_settings


async def workspace_model_registry(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    base_registry: ModelRegistry,
) -> ModelRegistry:
    """Clone the installed registry and add current discovered text models.

    Each dynamic adapter is bound to this workspace's encrypted connection
    revision. Nothing is added to the process-global registry.
    """
    registry = ModelRegistry()
    for installed in base_registry.list_models():
        registry.register(installed.manifest, installed.adapter)
    connections = list(
        (
            await session.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.workspace_id == workspace_id,
                    ProviderConnection.provider_type == "litellm",
                    ProviderConnection.protocol_profile == "openai_chat_v1",
                    ProviderConnection.enabled.is_(True),
                )
            )
        ).all()
    )
    for connection in connections:
        revision = await session.scalar(
            select(ProviderConnectionRevision)
            .where(ProviderConnectionRevision.connection_id == connection.id)
            .order_by(ProviderConnectionRevision.revision_no.desc())
            .limit(1)
        )
        if revision is None:
            continue
        evidence = await session.scalar(
            select(ProviderCapabilityEvidence)
            .where(
                ProviderCapabilityEvidence.connection_id == connection.id,
                ProviderCapabilityEvidence.capability == "auth_models",
                ProviderCapabilityEvidence.status == "passed",
                ProviderCapabilityEvidence.connection_revision_id == revision.id,
            )
            .order_by(ProviderCapabilityEvidence.tested_at.desc())
        )
        if evidence is None:
            continue
        settings = await runtime_text_gateway_settings(session, connection=connection)
        for alias in evidence.discovered_model_ids or []:
            manifest = litellm_logical_manifest(alias).model_copy(
                update={
                    "id": f"litellm/{connection.id}/{alias}",
                }
            )
            manifest.metadata.update(
                {
                    "connection_id": str(connection.id),
                    "connection_revision_id": str(revision.id),
                    "credential_revision_id": str(revision.credential_revision_id),
                }
            )
            if registry.get_or_none(manifest.id) is None:
                registry.register(manifest, LiteLLMModelAdapter(manifest, settings=settings))
    bound_media = (
        await session.execute(
            select(ProviderModelBinding, ProviderConnection, ModelCatalogEntry)
            .join(ProviderConnection, ProviderConnection.id == ProviderModelBinding.connection_id)
            .join(ModelCatalogEntry, ModelCatalogEntry.id == ProviderModelBinding.catalog_entry_id)
            .where(
                ProviderModelBinding.workspace_id == workspace_id,
                ProviderConnection.workspace_id == workspace_id,
                ProviderModelBinding.enabled.is_(True),
                ProviderConnection.enabled.is_(True),
                ModelCatalogEntry.lifecycle == "active",
            )
        )
    ).all()
    for binding, connection, catalog in bound_media:
        if binding.capability_manifest_hash != catalog.contract_manifest_hash:
            continue
        if hash_manifest(catalog.capability_manifest_json) != catalog.contract_manifest_hash:
            continue
        manifest = to_v3_model_manifest(
            ModelCapabilityManifest.model_validate(catalog.capability_manifest_json),
            transport_profile_id=connection.protocol_profile,
        ).model_copy(
            update={
                "id": f"binding:{binding.id}",
                "display_name": f"{catalog.display_name} · {connection.display_name}",
            }
        )
        manifest.metadata.update(
            {
                "binding_id": str(binding.id),
                "connection_id": str(connection.id),
                "account_verified": binding.account_verified,
            }
        )
        registry.register(manifest)
    return registry
