"""V3 registry bootstrap (spec §32.1).

P0 uses trusted static plugins: a fixed, explicit plugin list, no entry-point
discovery. ``build_v3_registry`` registers the transport profiles and V3 model
manifests for the currently shipped providers (Agnes + Volcengine Ark), derived
from the same immutable catalog seeds the A+B engine reads — so the V3 view can
never disagree with the runtime engine about a model's capability contract.

The adapter slots are filled by :class:`LegacyAdapterBridge` (Phase 3), which
delegates I/O to the existing unified Compiler/Runtime. Until then the registry
is usable for capability/manifest queries but ``create`` on a V2 adapter raises.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.providers.adapter import ModelAdapter
from app.providers.capabilities import Capability
from app.providers.contracts.common import (
    ExecutionContext,
    ProviderCancelResult,
    ProviderCostResult,
    ProviderCreateResult,
    ProviderPollResult,
    ResolvedArtifact,
)
from app.providers.manifest import ModelCapabilityManifest, ModelManifest, to_v3_model_manifest
from app.providers.registry import ModelRegistry
from app.providers.translation import TranslationResult
from app.providers.transport import AuthSpec, PollSpec, TransportProfile
from app.providers.transport_registry import TransportRegistry

# Transport profiles. One profile per wire endpoint family; a model's
# CapabilitySpec picks its profile via ``transport_profile_id``.

AGNES_IMAGE_TRANSPORT = TransportProfile(
    id="agnes-image-v1",
    method="POST",
    path_template="/v1/images/generations",
    auth=AuthSpec(scheme="bearer"),
    content_type="application/json",
    request_encoding="json",
    response_mode="sync",
)

AGNES_VIDEO_TRANSPORT = TransportProfile(
    id="agnes-video-v1",
    method="POST",
    path_template="/v1/videos",
    auth=AuthSpec(scheme="bearer"),
    content_type="application/json",
    request_encoding="json",
    response_mode="async_poll",
    poll=PollSpec(method="GET", path_template="/v1/videos/{id}"),
    cancel_path_template=None,
)

ARK_IMAGE_TRANSPORT = TransportProfile(
    id="ark-image-v1",
    method="POST",
    path_template="/images/generations",
    auth=AuthSpec(scheme="bearer"),
    content_type="application/json",
    request_encoding="json",
    response_mode="sync",
)

ARK_VIDEO_TRANSPORT = TransportProfile(
    id="ark-video-v1",
    method="POST",
    path_template="/contents/generations/tasks",
    auth=AuthSpec(scheme="bearer"),
    content_type="application/json",
    request_encoding="json",
    response_mode="async_poll",
    poll=PollSpec(
        method="GET",
        path_template="/contents/generations/tasks/{id}",
        default_interval_seconds=5.0,
    ),
    cancel_path_template="/contents/generations/tasks/{id}",
)

# (provider_type, protocol_profile, media_kind) -> transport profile id.
_TRANSPORT_BY_KEY: dict[tuple[str, str, str], str] = {
    ("agnes", "agnes_cn_v1", "image"): AGNES_IMAGE_TRANSPORT.id,
    ("agnes", "agnes_cn_v1", "video"): AGNES_VIDEO_TRANSPORT.id,
    ("volcengine", "ark_cn_v1", "image"): ARK_IMAGE_TRANSPORT.id,
    ("volcengine", "ark_cn_v1", "video"): ARK_VIDEO_TRANSPORT.id,
}


class UnavailableAdapter:
    """LEGACY_COMPAT: Phase 2 placeholder. Real ModelAdapter V2 bridges are
    registered by Phase 3 (:mod:`app.providers.adapters_v2`). This stub keeps
    the registry complete for capability/manifest queries while never sending a
    wire request."""

    def __init__(self, manifest: ModelManifest) -> None:
        self._manifest = manifest
        self.provider_id = manifest.provider_id
        self.model_id = manifest.id

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    async def translate(
        self,
        capability: Capability,
        request: Any,
        resolved_artifacts: dict[str, ResolvedArtifact],
    ) -> TranslationResult:
        raise NotImplementedError(
            "V2 adapter is not wired yet (Phase 3); registry is query-only"
        )

    async def create(
        self,
        capability: Capability,
        request: Any,
        context: ExecutionContext,
    ) -> ProviderCreateResult:
        raise NotImplementedError(
            "V2 adapter is not wired yet (Phase 3); registry is query-only"
        )

    async def poll(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderPollResult:
        raise NotImplementedError("V2 adapter is not wired yet (Phase 3)")

    async def cancel(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCancelResult:
        raise NotImplementedError("V2 adapter is not wired yet (Phase 3)")

    async def fetch_cost(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCostResult:
        raise NotImplementedError("V2 adapter is not wired yet (Phase 3)")


def _register_transports(registry: TransportRegistry) -> None:
    for profile in (
        AGNES_IMAGE_TRANSPORT,
        AGNES_VIDEO_TRANSPORT,
        ARK_IMAGE_TRANSPORT,
        ARK_VIDEO_TRANSPORT,
    ):
        if registry.get_or_none(profile.id) is None:
            registry.register(profile)


def _register_model(
    model_registry: ModelRegistry,
    transport_registry: TransportRegistry,
    manifest: ModelCapabilityManifest,
    adapter_factory: Callable[[ModelManifest], ModelAdapter] | None,
) -> None:
    key = (manifest.provider_type, manifest.protocol_profile, manifest.media_kind)
    transport_profile_id = _TRANSPORT_BY_KEY.get(key)
    if transport_profile_id is None:
        return
    transport_profile = transport_registry.get(transport_profile_id)
    v3_manifest = to_v3_model_manifest(manifest, transport_profile_id=transport_profile.id)
    # Phase 3 replaces the placeholder with a real bridge; both share the same
    # signature so bootstrap does not change.
    adapter = (
        adapter_factory(v3_manifest)
        if adapter_factory is not None
        else UnavailableAdapter(v3_manifest)
    )
    model_registry.register(v3_manifest, adapter)


def build_v3_registry(
    *,
    adapter_factories: dict[str, Callable[[ModelManifest], ModelAdapter]] | None = None,
    seed_manifests: list[ModelCapabilityManifest] | None = None,
) -> tuple[ModelRegistry, TransportRegistry]:
    """Build the V3 model + transport registries from the current catalog seeds.

    ``adapter_factories`` maps a V3 model id to a callable building its V2
    adapter (Phase 3). When absent, query-only placeholder adapters are used.
    """
    from app.providers.catalog_seed_data import seed_manifests_for

    model_registry = ModelRegistry()
    transport_registry = TransportRegistry()
    _register_transports(transport_registry)

    manifests = seed_manifests or [
        ModelCapabilityManifest.model_validate(item)
        for item in (
            list(seed_manifests_for(provider_type="agnes"))
            + list(seed_manifests_for(provider_type="volcengine"))
        )
    ]
    for manifest in manifests:
        v3_id = f"{manifest.provider_type}/{manifest.model_id}"
        factory = (adapter_factories or {}).get(v3_id)
        _register_model(model_registry, transport_registry, manifest, factory)
    return model_registry, transport_registry


def default_v3_registry() -> tuple[ModelRegistry, TransportRegistry]:
    """Module-level singleton used by API endpoints / routers. Adapters are
    real V2 bridges over the unified A+B runtime: one bridge per seeded model,
    built from the provider plugin's compiler + runtime factories. A bridge
    submits only when the underlying provider is configured (settings key);
    otherwise it fails closed exactly like the runtime does."""
    from app.config import get_settings
    from app.providers.adapters_v2 import BridgeComponents, LegacyAdapterBridge
    from app.providers.catalog_seed_data import seed_manifests_for
    from app.providers.registry import get_plugin

    factories: dict[str, Callable[[ModelManifest], ModelAdapter]] = {}

    def build(media_kind: str, manifest_dict: dict[str, Any]) -> None:
        a_b = ModelCapabilityManifest.model_validate(manifest_dict)
        v3_id = f"{a_b.provider_type}/{a_b.model_id}"
        plugin = get_plugin(a_b.provider_type, a_b.protocol_profile)
        if plugin.runtime_factory is None or plugin.compiler_factory is None:
            return
        image_compiler, video_compiler = plugin.compiler_factory()
        runtime = plugin.runtime_factory(
            settings=get_settings(),
            host=plugin.default_base_url,
        )

        def factory(v3_manifest: ModelManifest) -> ModelAdapter:
            return LegacyAdapterBridge(
                v3_manifest,
                BridgeComponents(
                    a_b_manifest=a_b,
                    image_compiler=image_compiler if media_kind == "image" else None,
                    video_compiler=video_compiler if media_kind == "video" else None,
                    runtime=runtime,
                ),
                invoke_model_value=a_b.model_id,
            )

        factories[v3_id] = factory

    for manifest_dict in seed_manifests_for(provider_type="agnes"):
        build(manifest_dict["media_kind"], manifest_dict)
    for manifest_dict in seed_manifests_for(provider_type="volcengine"):
        build(manifest_dict["media_kind"], manifest_dict)
    return build_v3_registry(adapter_factories=factories)
