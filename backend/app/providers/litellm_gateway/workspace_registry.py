"""Workspace-scoped text model capability plugins from persisted discovery."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.litellm_adapter import LiteLLMModelAdapter
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
from app.providers.models import (
    ProviderCapabilityEvidence,
    ProviderConnection,
    ProviderConnectionRevision,
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
    connection = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == workspace_id,
            ProviderConnection.provider_type == "litellm",
            ProviderConnection.protocol_profile == "openai_chat_v1",
            ProviderConnection.enabled.is_(True),
        )
    )
    if connection is None:
        return registry
    revision = await session.scalar(
        select(ProviderConnectionRevision)
        .where(ProviderConnectionRevision.connection_id == connection.id)
        .order_by(ProviderConnectionRevision.revision_no.desc())
        .limit(1)
    )
    if revision is None:
        return registry
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
        return registry
    settings = await runtime_text_gateway_settings(session, connection=connection)
    for alias in evidence.discovered_model_ids or []:
        manifest = litellm_logical_manifest(alias)
        if registry.get_or_none(manifest.id) is None:
            registry.register(manifest, LiteLLMModelAdapter(manifest, settings=settings))
    return registry
