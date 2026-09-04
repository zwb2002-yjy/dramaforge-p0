"""Provider plugin registry.

A :class:`ProviderPlugin` is the extension point for a model supplier: it
describes one ``(provider_type, protocol_profile)`` pair — its default host,
BYOK credential key, model contracts, capability→purpose mapping, and how to
build the protocol client used for account verification.

Adding a supplier means registering a plugin; execution code resolves plugins
from the registry instead of branching on provider names. A plugin may be
registered as catalog-only (``implemented=False``) before its adapter exists;
the API and connection service refuse to use a not-implemented plugin.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.providers.adapter import ModelAdapter
from app.providers.capabilities import Capability, capability_satisfied
from app.providers.manifest import ModelManifest

# (settings, host) -> protocol client. The client exposes the create/poll surface
# used by capability probes (create_image / create_video / poll_video).
ClientFactory = Callable[[Settings, str | None], Any]


@dataclass(frozen=True)
class ProviderPlugin:
    provider_type: str
    protocol_profile: str
    display_name: str
    default_base_url: str
    # Whether the protocol client is implemented. Catalog-only plugins cannot be
    # used to create connections or run probes.
    implemented: bool = False
    # BYOK credential slot key; defaults to provider_type.
    credential_provider_key: str | None = None
    # Settings field prefix (``<prefix>_enabled/api_key/base_url/...``); defaults
    # to provider_type.
    settings_prefix: str | None = None
    # (media_type, purpose) -> model id that this profile is allowed to bind.
    # DEPRECATED in favor of catalog_manifests; retained for legacy validation.
    model_contracts: dict[tuple[str, str], str] = field(default_factory=dict)
    # capability -> purpose advanced by account verification (image_i2i->keyframe).
    capability_purposes: dict[str, str] = field(default_factory=dict)
    # Capabilities that spend real budget and require an explicit authorization.
    paid_capabilities: frozenset[str] = frozenset()
    # How an image I2I capability probe carries its canonical artifact. The
    # connection service routes by this declared protocol contract, never by
    # supplier name.
    image_i2i_probe_transport: str = "bytes"
    # Path suffix (on default_base_url) used by the auth_models capability probe.
    model_list_path: str = "/v1/models"
    client_factory: ClientFactory | None = None
    # Versioned capability manifests shipped with the plugin (current seed).
    catalog_manifests: tuple[dict[str, Any], ...] = ()
    # Factories for the unified runtime/compiler surface (stages B1-B3).
    runtime_factory: Callable[..., Any] | None = None
    compiler_factory: Callable[..., Any] | None = None

    @property
    def credential_key(self) -> str:
        return self.credential_provider_key or self.provider_type

    @property
    def prefix(self) -> str:
        return self.settings_prefix or self.provider_type

    def build_client(self, settings: Settings, *, host: str | None = None) -> Any:
        if self.client_factory is None:
            raise NotImplementedError(
                f"provider plugin {self.provider_type}/{self.protocol_profile} "
                "has no protocol client implementation"
            )
        return self.client_factory(settings, host)


_registry: dict[tuple[str, str], ProviderPlugin] = {}


def register_plugin(plugin: ProviderPlugin) -> None:
    key = (plugin.provider_type, plugin.protocol_profile)
    if key in _registry:
        raise ValueError(f"provider plugin already registered: {key[0]}/{key[1]}")
    _registry[key] = plugin


def get_plugin(provider_type: str, protocol_profile: str) -> ProviderPlugin:
    plugin = _registry.get((provider_type, protocol_profile))
    if plugin is None:
        raise LookupError(f"unknown provider plugin: {provider_type}/{protocol_profile}")
    return plugin


def list_plugins() -> list[ProviderPlugin]:
    return sorted(
        _registry.values(),
        key=lambda p: (p.provider_type, p.protocol_profile),
    )


def implemented_plugins() -> list[ProviderPlugin]:
    return sorted(
        (p for p in _registry.values() if p.implemented),
        key=lambda p: (p.provider_type, p.protocol_profile),
    )


def _agnes_hub_client(settings: Settings, host: str | None) -> Any:
    from app.providers.agnes import AgnesHubClient

    return AgnesHubClient(settings, host=host)


def _ark_hub_client(settings: Settings, host: str | None) -> Any:
    from app.providers.volcengine import ArkHubClient

    return ArkHubClient(settings, host=host)


def _minimax_hub_client(settings: Settings, host: str | None) -> Any:
    from app.providers.minimax import MiniMaxHubClient

    return MiniMaxHubClient(settings, host=host)


def _register_defaults() -> None:
    from app.providers.agnes import (
        AGNES_CN_HOST,
        AGNES_CN_PROFILE,
        _agnes_compiler_factory,
        _agnes_runtime_factory,
    )
    from app.providers.catalog_seed_data import seed_manifests_for

    register_plugin(
        ProviderPlugin(
            provider_type="agnes",
            protocol_profile=AGNES_CN_PROFILE,
            display_name="Agnes 中国站",
            default_base_url=AGNES_CN_HOST,
            implemented=True,
            settings_prefix="agnes",
            credential_provider_key="agnes",
            model_contracts={
                ("image", "keyframe"): "agnes-image-2.1-flash",
                ("video", "video"): "agnes-video-v2.0",
            },
            capability_purposes={"image_i2i": "keyframe", "video_i2v": "video"},
            paid_capabilities=frozenset({"image_t2i", "image_i2i", "video_i2v"}),
            model_list_path="/v1/models",
            client_factory=_agnes_hub_client,
            catalog_manifests=tuple(seed_manifests_for(provider_type="agnes")),
            runtime_factory=_agnes_runtime_factory,
            compiler_factory=_agnes_compiler_factory,
        )
    )
    from app.providers.minimax import (
        MINIMAX_CN_HOST,
        MINIMAX_CN_PROFILE,
        _minimax_compiler_factory,
        _minimax_runtime_factory,
    )

    register_plugin(
        ProviderPlugin(
            provider_type="minimax",
            protocol_profile=MINIMAX_CN_PROFILE,
            display_name="MiniMax",
            default_base_url=MINIMAX_CN_HOST,
            implemented=True,
            settings_prefix="minimax",
            credential_provider_key="minimax",
            model_contracts={
                ("image", "keyframe"): "image-01",
                ("video", "video"): "MiniMax-H3",
            },
            capability_purposes={"image_i2i": "keyframe", "video_i2v": "video"},
            paid_capabilities=frozenset({"image_i2i", "video_i2v"}),
            image_i2i_probe_transport="public_url",
            model_list_path="/v1/models",
            client_factory=_minimax_hub_client,
            catalog_manifests=tuple(seed_manifests_for(provider_type="minimax")),
            runtime_factory=_minimax_runtime_factory,
            compiler_factory=_minimax_compiler_factory,
        )
    )
    # Ark data-plane contract (Seedream image + Seedance video) verified via
    # arkcli +gen --dry-run and official Volcengine docs 2026-08-07. The host
    # carries the /api/v3 prefix; wire paths are appended by the adapter.
    from app.providers.volcengine import (
        _ark_compiler_factory,
        _ark_runtime_factory,
    )

    register_plugin(
        ProviderPlugin(
            provider_type="volcengine",
            protocol_profile="ark_cn_v1",
            display_name="火山方舟",
            default_base_url="https://ark.cn-beijing.volces.com/api/v3",
            implemented=True,
            settings_prefix="volcengine",
            credential_provider_key="volcengine",
            model_contracts={
                ("image", "keyframe"): "doubao-seedream-4-0-250828",
                ("video", "video"): "doubao-seedance-2-0-260128",
            },
            capability_purposes={"image_i2i": "keyframe", "video_i2v": "video"},
            paid_capabilities=frozenset({"image_t2i", "image_i2i", "video_i2v"}),
            # TODO(phase-d): confirm whether the Ark data plane exposes a model
            # list endpoint; the auth_models probe may need a different check.
            model_list_path="/models",
            client_factory=_ark_hub_client,
            catalog_manifests=tuple(seed_manifests_for(provider_type="volcengine")),
            runtime_factory=_ark_runtime_factory,
            compiler_factory=_ark_compiler_factory,
        )
    )


_register_defaults()


# ---------------------------------------------------------------------------
# V3 model registry (spec §30).
# Distinct from the ProviderPlugin registry above: plugins describe one
# (provider_type, protocol_profile) — connections, credentials, probes. The
# ModelRegistry is the model-level capability+adapter index that the
# CapabilityRouter resolves against. RegisteredModel bundles the V3 manifest
# with the adapter that speaks for that model.
# ---------------------------------------------------------------------------


class DuplicateModelError(ValueError):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"model already registered: {model_id}")


class UnknownModelError(LookupError):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"unknown model: {model_id}")


@dataclass(frozen=True)
class RegisteredModel:
    manifest: ModelManifest
    adapter: ModelAdapter


class ModelRegistry:
    """In-memory model index (P0 static plugins; spec §32.1). All methods are
    synchronous — registration happens once at bootstrap."""

    def __init__(self) -> None:
        self._models: dict[str, RegisteredModel] = {}

    def register(self, manifest: ModelManifest, adapter: ModelAdapter) -> None:
        if manifest.id in self._models:
            raise DuplicateModelError(manifest.id)
        self._models[manifest.id] = RegisteredModel(manifest=manifest, adapter=adapter)

    def get(self, model_id: str) -> RegisteredModel:
        model = self._models.get(model_id)
        if model is None:
            raise UnknownModelError(model_id)
        return model

    def get_or_none(self, model_id: str) -> RegisteredModel | None:
        return self._models.get(model_id)

    def list_models(self) -> list[RegisteredModel]:
        return sorted(self._models.values(), key=lambda item: item.manifest.id)

    def find_by_capability(self, capability: Capability) -> list[RegisteredModel]:
        return [
            model
            for model in sorted(self._models.values(), key=lambda item: item.manifest.id)
            if capability in model.manifest.capability_specs
            or capability_satisfied(
                capability,
                _declared_fine_grained(model.manifest),
            )
        ]


def _declared_fine_grained(manifest: ModelManifest) -> set[str]:
    """Best-effort fine-grained capability set from a V3 manifest. V3 manifests
    built from the A+B catalog carry the fine-grained names inside
    ``metadata``; the capability_specs keys remain the source of truth."""
    declared: set[str] = set()
    for spec in manifest.capability_specs.values():
        declared.add(str(spec.capability))
    raw = manifest.metadata.get("fine_grained_capabilities")
    if isinstance(raw, list):
        declared.update(str(item) for item in raw)
    return declared
