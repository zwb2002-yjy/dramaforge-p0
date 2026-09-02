"""Workspace-scoped CapabilityRouter construction (V3 Phase 11).

The V3 router normally resolves a model from the static registry. For business
paths that hold a workspace but no shot binding (e.g. canonical lead portrait),
the adapter must use the workspace's BYOK credential. This module builds a
:class:`ProviderAdapterBridge` for one provider/profile/media from the workspace's
enabled connection, so business code goes through the same
``CapabilityRouter → Adapter → Runtime`` surface instead of a provider getter.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.providers.adapters_v2 import BridgeComponents, ProviderAdapterBridge
from app.providers.bootstrap import transport_profile_id_for
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.manifest import ModelCapabilityManifest, to_v3_model_manifest
from app.providers.models import ProviderConnection
from app.providers.registry import get_plugin
from app.providers.runtime import ProviderRuntimeResolver
from app.providers.workspace_credentials import runtime_connection_settings
from app.shared.errors import NotFoundError, ValidationAppError


def select_seed_manifest(
    manifests: list[dict[str, object]], media_kind: str
) -> ModelCapabilityManifest:
    """Pick the manifest for one media kind (HIGH-4).

    Never rely on the seed list's array position — a provider may ship several
    image/video models. Deterministic first match by ``media_kind``; fail closed
    when the provider has no manifest for the requested media kind.
    """
    for item in manifests:
        if item.get("media_kind") == media_kind:
            return ModelCapabilityManifest.model_validate(item)
    raise ValidationAppError(
        f"no {media_kind} catalog manifest for provider",
        details={"code": "PROVIDER_RUNTIME_UNAVAILABLE", "media_kind": media_kind},
    )


async def resolve_workspace_bridge(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider_type: str,
    media_kind: str,
    settings: Settings | None = None,
) -> ProviderAdapterBridge:
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
    a_b = select_seed_manifest(manifests, media_kind=media_kind)
    # HIGH-3: the transport identity must be the registered profile id, resolved
    # from the connection's provider/profile/media — never a string guess.
    transport_profile_id = transport_profile_id_for(
        connection.provider_type, connection.protocol_profile, media_kind
    )
    if transport_profile_id is None:
        raise ValidationAppError(
            f"no registered transport for {connection.provider_type}/"
            f"{connection.protocol_profile}/{media_kind}",
            details={"code": "PROVIDER_RUNTIME_UNAVAILABLE"},
        )
    v3 = to_v3_model_manifest(a_b, transport_profile_id=transport_profile_id)
    image_compiler = resolved.image_compiler if media_kind == "image" else None
    video_compiler = resolved.video_compiler if media_kind == "video" else None
    return ProviderAdapterBridge(
        v3,
        BridgeComponents(
            a_b_manifest=a_b,
            image_compiler=image_compiler,
            video_compiler=video_compiler,
            runtime=resolved.runtime,
        ),
        invoke_model_value=a_b.model_id,
    )
