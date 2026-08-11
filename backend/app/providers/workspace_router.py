"""Workspace-scoped CapabilityRouter construction (V3 Phase 11).

The V3 router normally resolves a model from the static registry. For business
paths that hold a workspace but no shot binding (e.g. canonical lead portrait),
the adapter must use the workspace's BYOK credential. This module builds a
:class:`LegacyAdapterBridge` for one provider/profile/media from the workspace's
enabled connection, so business code goes through the same
``CapabilityRouter → Adapter → Runtime`` surface instead of a provider getter.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.providers.adapters_v2 import BridgeComponents, LegacyAdapterBridge
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.models import ProviderConnection
from app.providers.registry import get_plugin
from app.providers.runtime import ProviderRuntimeResolver
from app.providers.workspace_credentials import runtime_connection_settings
from app.shared.errors import NotFoundError, ValidationAppError

# (provider_type, media_kind) -> seed manifest index within the provider.
_MEDIA_INDEX = {"image": 0, "video": 1}


async def resolve_workspace_bridge(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider_type: str,
    media_kind: str,
    settings: Settings | None = None,
) -> LegacyAdapterBridge:
    """Build a V2 bridge for the workspace's enabled connection of
    ``provider_type``, wired to the BYOK credential and connection host."""
    connection = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == workspace_id,
            ProviderConnection.provider_type == provider_type,
            ProviderConnection.enabled.is_(True),
        )
    )
    if connection is None:
        raise NotFoundError(
            f"no enabled provider connection for {provider_type} in this workspace"
        )
    plugin = get_plugin(connection.provider_type, connection.protocol_profile)
    if plugin.runtime_factory is None or plugin.compiler_factory is None:
        raise ValidationAppError(
            f"provider {provider_type} has no unified runtime",
            details={"code": "PROVIDER_RUNTIME_UNAVAILABLE"},
        )
    cfg = await runtime_connection_settings(session, connection=connection, settings=settings)
    resolved = await ProviderRuntimeResolver(session).resolve(
        plugin=plugin,
        connection=connection,
        binding=None,  # type: ignore[arg-type]
        entry=None,  # type: ignore[arg-type]
        settings=cfg,
    )
    manifests = seed_manifests_for(provider_type=provider_type)
    if not manifests:
        raise ValidationAppError(
            f"no catalog manifest for provider {provider_type}",
            details={"code": "PROVIDER_RUNTIME_UNAVAILABLE"},
        )
    index = _MEDIA_INDEX.get(media_kind, 0)
    a_b = ModelCapabilityManifest.model_validate(manifests[index])
    transport_profile_id = f"{provider_type}-{media_kind}-v1"
    v3 = to_v3_model_manifest(a_b, transport_profile_id=transport_profile_id)
    image_compiler = resolved.image_compiler if media_kind == "image" else None
    video_compiler = resolved.video_compiler if media_kind == "video" else None
    return LegacyAdapterBridge(
        v3,
        BridgeComponents(
            a_b_manifest=a_b,
            image_compiler=image_compiler,
            video_compiler=video_compiler,
            runtime=resolved.runtime,
        ),
        invoke_model_value=a_b.model_id,
    )
