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
    model_contracts: dict[tuple[str, str], str] = field(default_factory=dict)
    # capability -> purpose advanced by account verification (image_i2i->keyframe).
    capability_purposes: dict[str, str] = field(default_factory=dict)
    # Capabilities that spend real budget and require an explicit authorization.
    paid_capabilities: frozenset[str] = frozenset()
    # Path suffix (on default_base_url) used by the auth_models capability probe.
    model_list_path: str = "/v1/models"
    client_factory: ClientFactory | None = None

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
        raise LookupError(
            f"unknown provider plugin: {provider_type}/{protocol_profile}"
        )
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


def _register_defaults() -> None:
    from app.providers.agnes import AGNES_CN_HOST, AGNES_CN_PROFILE

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
        )
    )
    # Catalog-only until the ark_cn_v1 adapter lands (Phase B). The model ids and
    # model_list_path below are forward references to be contract-verified then.
    register_plugin(
        ProviderPlugin(
            provider_type="volcengine",
            protocol_profile="ark_cn_v1",
            display_name="火山方舟",
            default_base_url="https://ark.cn-beijing.volces.com/api/v3",
            implemented=False,
            settings_prefix="volcengine",
            credential_provider_key="volcengine",
            model_contracts={
                ("image", "keyframe"): "doubao-seedream-4-0-250828",
                ("video", "video"): "doubao-seedance-1-0-pro-250528",
            },
            capability_purposes={"image_i2i": "keyframe", "video_i2v": "video"},
            paid_capabilities=frozenset({"image_t2i", "image_i2i", "video_i2v"}),
            model_list_path="/models",  # TODO(phase-b): verify Ark data-plane model list path
        )
    )


_register_defaults()
