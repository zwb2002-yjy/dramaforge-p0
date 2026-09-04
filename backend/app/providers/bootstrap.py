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
from app.providers.capabilities import Capability
from app.providers.contracts.common import (
    ExecutionContext,
    ProviderCancelResult,
    ProviderCostResult,
    ProviderCreateResult,
    ProviderPollResult,
    ResolvedArtifact,
)
from app.providers.manifest import (
    CapabilitySpec,
    ModelCapabilityManifest,
    ModelManifest,
    ParameterSpec,
    SubmissionSemantics,
    to_v3_model_manifest,
)
from app.providers.registry import ModelRegistry
from app.providers.translation import TranslationResult
from app.providers.transport import AuthSpec, PollSpec, TransportProfile
from app.providers.transport_registry import TransportRegistry

# The LiteLLM text model registered in the default V3 registry (M7/M8). The
# manifest carries a ``ModelBackendBinding`` so the generic adapter knows which
# gateway model to send. P0 exposes ``text.generate`` through the gateway.
# The text-llm model is a *bootstrap bridge* (fix spec §34/§103): it maps to the
# configurable ``compatibility-text`` logical alias so the gateway can serve the compatibility
# BYOK text path while logical aliases (script-quality / script-fast) are
# registered separately by :func:`register_litellm_logical_models`.
LITELLM_TEXT_MODEL_ID = "litellm/text-llm"

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
        raise NotImplementedError("V2 adapter is not wired yet (Phase 3); registry is query-only")

    async def create(
        self,
        capability: Capability,
        request: Any,
        context: ExecutionContext,
    ) -> ProviderCreateResult:
        raise NotImplementedError("V2 adapter is not wired yet (Phase 3); registry is query-only")

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
            + list(seed_manifests_for(provider_type="minimax"))
        )
    ]
    for manifest in manifests:
        v3_id = f"{manifest.provider_type}/{manifest.model_id}"
        factory = (adapter_factories or {}).get(v3_id)
        _register_model(model_registry, transport_registry, manifest, factory)
    return model_registry, transport_registry


def litellm_text_manifest() -> ModelManifest:
    """V3 manifest for the generic LiteLLM text model (spec §113/§114).

    Bootstrap bridge (fix spec §34/§103): the ``gateway_model`` is the configurable
    logical alias, NOT an upstream provider
    model (fix spec §32/§33 — DramaForge requests a logical group; LiteLLM's
    Router picks the deployment). Prefer ``litellm/<logical-alias>`` models
    registered by :func:`register_litellm_logical_models` in new profiles.
    """
    from app.config import get_settings
    from app.providers.model_profiles.models import ModelBackendBinding

    settings = get_settings()
    backend = ModelBackendBinding(
        kind="litellm",
        gateway_model=settings.litellm_text_gateway_model or "legacy-text",
        api_mode="chat",
        provider_id="litellm",
        model_family="litellm",
    )
    return ModelManifest(
        schema_version="1",
        manifest_version="1",
        id=LITELLM_TEXT_MODEL_ID,
        provider_id="litellm",
        model_name="text-llm",
        display_name="LiteLLM 文本模型（provider adapter bridge）",
        model_family="litellm",
        capability_specs={
            Capability.TEXT_GENERATE: CapabilitySpec(
                capability=Capability.TEXT_GENERATE,
                common_options={
                    "max_tokens": ParameterSpec(type="integer", ui_component="number"),
                    "system": ParameterSpec(type="string", ui_component="textarea"),
                    "temperature": ParameterSpec(type="number", ui_component="number"),
                },
                native_options={},
                transport_profile_id="litellm-chat-v1",
            )
        },
        execution_mode="sync",
        supports_cancel=False,
        submission_semantics=SubmissionSemantics(),
        metadata={
            "backend": backend.model_dump(mode="json"),
            "legacy_compat": True,
            "bootstrap_bridge": True,
        },
    )


def register_litellm_text_models(
    model_registry: ModelRegistry,
    *,
    adapter_factory: Callable[[ModelManifest], ModelAdapter] | None = None,
) -> None:
    """Register the LiteLLM text model(s) in a V3 registry (M7)."""
    from app.providers.litellm_adapter import LiteLLMModelAdapter

    manifest = litellm_text_manifest()
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
    from app.config import get_settings
    from app.providers.adapters_v2 import BridgeComponents, ProviderAdapterBridge
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

    for manifest_dict in seed_manifests_for(provider_type="agnes"):
        build(manifest_dict["media_kind"], manifest_dict)
    for manifest_dict in seed_manifests_for(provider_type="volcengine"):
        build(manifest_dict["media_kind"], manifest_dict)
    for manifest_dict in seed_manifests_for(provider_type="minimax"):
        build(manifest_dict["media_kind"], manifest_dict)
    registry, transport_registry = build_v3_registry(adapter_factories=factories)
    register_litellm_text_models(registry)
    # Static logical aliases (script-quality / script-fast, fix spec §34/§104).
    # Discovery sync (F8) can add more aliases from GET /v1/models later.
    from app.providers.litellm_gateway.model_catalog import (
        register_litellm_logical_models,
    )

    register_litellm_logical_models(registry)
    return registry, transport_registry
