"""V3 registry bootstrap (spec §32.1).

P0 uses trusted static plugins: a fixed, explicit plugin list, no entry-point
discovery. ``build_v3_registry`` registers the transport profiles and V3 model
manifests for the currently shipped providers (Agnes + Volcengine Ark), derived
from the same immutable catalog seeds the A+B engine reads — so the V3 view can
never disagree with the runtime engine about a model's capability contract.

The adapter slots are filled by :class:`ProviderAdapterBridge` (Phase 3), which
delegates I/O to the existing unified Compiler/Runtime. Until then the registry
is usable for capability/manifest queries but ``create`` on a V2 adapter raises.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.providers.adapter import ModelAdapter
from app.providers.manifest import (
    ModelCapabilityManifest,
    ModelManifest,
    to_v3_model_manifest,
)
from app.providers.registry import ModelRegistry
from app.providers.transport import AuthSpec, PollSpec, TransportProfile
from app.providers.transport_registry import TransportRegistry

# The LiteLLM text model registered in the default V3 registry (M7/M8). The
# manifest carries a ``ModelBackendBinding`` so the generic adapter knows which
# gateway model to send. P0 exposes ``text.generate`` through the gateway.
# The text model is the bootstrap identity for the configured LiteLLM logical
# alias. The canonical aliases (script-quality / script-fast) are registered by
# :func:`register_litellm_logical_models` and route through the same gateway.
DEFAULT_TEXT_MODEL_ID = "litellm/script-quality"

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

MINIMAX_IMAGE_TRANSPORT = TransportProfile(
    id="minimax-image-v1",
    method="POST",
    path_template="/v1/image_generation",
    auth=AuthSpec(scheme="bearer"),
    content_type="application/json",
    request_encoding="json",
    response_mode="sync",
)

MINIMAX_VIDEO_TRANSPORT = TransportProfile(
    id="minimax-video-v2",
    method="POST",
    path_template="/v2/video_generation",
    auth=AuthSpec(scheme="bearer"),
    content_type="application/json",
    request_encoding="json",
    response_mode="async_poll",
    poll=PollSpec(
        method="GET", path_template="/v2/query/video_generation/{id}", default_interval_seconds=5.0
    ),
    cancel_path_template="/v2/video_generation/{id}",
)

# (provider_type, protocol_profile, media_kind) -> transport profile id.
_TRANSPORT_BY_KEY: dict[tuple[str, str, str], str] = {
    ("agnes", "agnes_cn_v1", "image"): AGNES_IMAGE_TRANSPORT.id,
    ("agnes", "agnes_cn_v1", "video"): AGNES_VIDEO_TRANSPORT.id,
    ("volcengine", "ark_cn_v1", "image"): ARK_IMAGE_TRANSPORT.id,
    ("volcengine", "ark_cn_v1", "video"): ARK_VIDEO_TRANSPORT.id,
    ("minimax", "minimax_cn_v1", "image"): MINIMAX_IMAGE_TRANSPORT.id,
    ("minimax", "minimax_cn_v1", "video"): MINIMAX_VIDEO_TRANSPORT.id,
}


def transport_profile_id_for(
    provider_type: str, protocol_profile: str, media_kind: str
) -> str | None:
    """Resolve the registered transport profile id for a provider/profile/media.

    Single source of truth (HIGH-3): never guess ``f"{provider_type}-{media}-v1"``
    — e.g. volcengine uses ``ark-image-v1``, not ``volcengine-image-v1``. Returns
    ``None`` when no transport is registered for the combination.
    """
    return _TRANSPORT_BY_KEY.get((provider_type, protocol_profile, media_kind))


LITELLM_CHAT_TRANSPORT = TransportProfile(
    id="litellm-chat-v1",
    method="POST",
    path_template="/v1/chat/completions",
    auth=AuthSpec(scheme="bearer"),
    content_type="application/json",
    request_encoding="json",
    response_mode="sync",
)


def _register_transports(registry: TransportRegistry) -> None:
    for profile in (
        AGNES_IMAGE_TRANSPORT,
        AGNES_VIDEO_TRANSPORT,
        ARK_IMAGE_TRANSPORT,
        ARK_VIDEO_TRANSPORT,
        MINIMAX_IMAGE_TRANSPORT,
        MINIMAX_VIDEO_TRANSPORT,
        LITELLM_CHAT_TRANSPORT,
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
        raise ValueError(f"model catalog has no registered transport profile for {key}")
    transport_profile = transport_registry.get(transport_profile_id)
    v3_manifest = to_v3_model_manifest(manifest, transport_profile_id=transport_profile.id)
    v3_manifest.metadata["inspection_only"] = True
    adapter = adapter_factory(v3_manifest) if adapter_factory is not None else None
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
    from app.providers.catalog_loader import active_manifests_for

    model_registry = ModelRegistry()
    transport_registry = TransportRegistry()
    _register_transports(transport_registry)

    if seed_manifests is None:
        manifests = [
            ModelCapabilityManifest.model_validate(item)
            for item in (
                list(active_manifests_for(provider_type="agnes"))
                + list(active_manifests_for(provider_type="volcengine"))
                + list(active_manifests_for(provider_type="minimax"))
            )
            if item.get("catalog_source") != "protocol_contract"
        ]
    else:
        manifests = seed_manifests
    for manifest in manifests:
        v3_id = f"{manifest.provider_type}/{manifest.model_id}"
        factory = (adapter_factories or {}).get(v3_id)
        _register_model(model_registry, transport_registry, manifest, factory)
    return model_registry, transport_registry


def default_text_manifest() -> ModelManifest:
    """Use the same logical-model contract as every explicit text profile."""
    from app.config import get_settings
    from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest

    return litellm_logical_manifest(get_settings().litellm_text_gateway_model)


def register_default_text_model(
    model_registry: ModelRegistry,
    *,
    adapter_factory: Callable[[ModelManifest], ModelAdapter] | None = None,
) -> None:
    """Register the LiteLLM text model(s) in a V3 registry (M7)."""
    from app.providers.litellm_adapter import LiteLLMModelAdapter

    manifest = default_text_manifest()
    if model_registry.get_or_none(manifest.id) is not None:
        return
    adapter = (
        adapter_factory(manifest) if adapter_factory is not None else LiteLLMModelAdapter(manifest)
    )
    model_registry.register(manifest, adapter)


def default_v3_registry() -> tuple[ModelRegistry, TransportRegistry]:
    """Module-level singleton used by API endpoints / routers. Adapters are
    real V2 bridges over the unified A+B runtime: one bridge per seeded model,
    built from the provider plugin's compiler + runtime factories. A bridge
    submits only when the underlying provider is configured (settings key);
    otherwise it fails closed exactly like the runtime does."""
    from app.providers.adapters_v2 import BridgeComponents, ProviderAdapterBridge
    from app.providers.catalog_loader import active_manifests_for
    from app.providers.registry import get_plugin

    factories: dict[str, Callable[[ModelManifest], ModelAdapter]] = {}

    def build(media_kind: str, manifest_dict: dict[str, Any]) -> None:
        a_b = ModelCapabilityManifest.model_validate(manifest_dict)
        v3_id = f"{a_b.provider_type}/{a_b.model_id}"
        plugin = get_plugin(a_b.provider_type, a_b.protocol_profile)
        if plugin.runtime_factory is None or plugin.compiler_factory is None:
            return
        image_compiler, video_compiler = plugin.compiler_factory()
        # Catalog adapters only inspect and compile. Media submission belongs
        # exclusively to the frozen DB-bound Production execution path.
        runtime = None

        def factory(v3_manifest: ModelManifest) -> ModelAdapter:
            return ProviderAdapterBridge(
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

    for manifest_dict in active_manifests_for(provider_type="agnes"):
        build(manifest_dict["media_kind"], manifest_dict)
    for manifest_dict in active_manifests_for(provider_type="volcengine"):
        build(manifest_dict["media_kind"], manifest_dict)
    for manifest_dict in active_manifests_for(provider_type="minimax"):
        build(manifest_dict["media_kind"], manifest_dict)
    registry, transport_registry = build_v3_registry(adapter_factories=factories)
    register_default_text_model(registry)
    # Static logical aliases (script-quality / script-fast, fix spec §34/§104).
    # Discovery sync (F8) can add more aliases from GET /v1/models later.
    from app.providers.litellm_gateway.model_catalog import (
        register_litellm_logical_models,
    )

    register_litellm_logical_models(registry)
    return registry, transport_registry
