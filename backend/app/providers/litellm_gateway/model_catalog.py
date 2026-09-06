"""LiteLLM model discovery + logical alias sync (spec §35–§42, F8/F9).

``GET /v1/models`` exposes the gateway's configured logical aliases. A
discovered alias becomes a DramaForge V3 model ``litellm/<alias>`` with
``backend.gateway_model=<alias>`` and ``text.generate`` capability (spec §39:
plain LLM aliases default to TEXT_GENERATE; image/video/tts capabilities are
never guessed — media needs an explicit manifest, spec §83).

The same builder registers the *static* logical aliases configured in
``Settings.litellm_logical_models``, so a Profile can bind ``litellm/script-quality``
before the gateway is reachable (deterministic) while discovery keeps the
catalog in sync with the gateway afterwards (TTL-cached, best-effort).
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.providers.capabilities import Capability
from app.providers.manifest import (
    CapabilitySpec,
    ModelManifest,
    ParameterSpec,
    SubmissionSemantics,
)
from app.providers.model_profiles.models import ModelBackendBinding
from app.providers.registry import ModelRegistry

LITELLM_LOGICAL_PREFIX = "litellm/"
LITELLM_TRANSPORT_PROFILE_ID = "litellm-chat-v1"


def litellm_logical_manifest(alias: str) -> ModelManifest:
    """V3 manifest for one gateway logical alias (spec §41/§42)."""
    backend = ModelBackendBinding(
        kind="litellm",
        gateway_model=alias,
        api_mode="chat",
        provider_id="litellm",
        model_family="litellm",
    )
    return ModelManifest(
        schema_version="1",
        manifest_version="1",
        id=f"{LITELLM_LOGICAL_PREFIX}{alias}",
        provider_id="litellm",
        model_name=alias,
        display_name=f"LiteLLM {alias}",
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
                transport_profile_id=LITELLM_TRANSPORT_PROFILE_ID,
            )
        },
        execution_mode="sync",
        supports_cancel=False,
        submission_semantics=SubmissionSemantics(),
        metadata={
            "backend": backend.model_dump(mode="json"),
            "logical_alias": alias,
            "discovered": True,
        },
    )


def register_litellm_logical_models(
    registry: ModelRegistry,
    *,
    settings: Settings | None = None,
) -> list[str]:
    """Register the static logical aliases (spec §34) into a V3 registry.

    Guards duplicates so re-registration (or a later discovery sync) is a no-op.
    """
    from app.providers.litellm_adapter import LiteLLMModelAdapter

    cfg = settings or get_settings()
    aliases = [a for a in cfg.litellm_logical_models if a and a.strip()]
    registered: list[str] = []
    for alias in aliases:
        model_id = f"{LITELLM_LOGICAL_PREFIX}{alias.strip()}"
        if registry.get_or_none(model_id) is not None:
            continue
        manifest = litellm_logical_manifest(alias.strip())
        registry.register(manifest, LiteLLMModelAdapter(manifest, settings=cfg))
        registered.append(model_id)
    return registered


class LiteLLMModelCatalogSyncService:
    """Best-effort sync of gateway aliases into a registry (spec §37/§38).

    ``sync`` never raises on gateway errors — the gateway may be down while the
    app keeps running (spec §122). It returns the aliases that were *newly*
    registered this pass, which is also the discovery signal for callers.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        registry: ModelRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        from app.providers.litellm_gateway.client import LiteLLMGatewayClient

        self._client = client or LiteLLMGatewayClient(settings=settings)
        self._settings = settings or get_settings()
        self._registry = registry

    async def sync(
        self, registry: ModelRegistry | None = None
    ) -> list[str]:
        """Discover aliases and register missing ones as ``litellm/<alias>``.

        Returns the list of newly registered model ids. Raises nothing for
        gateway errors — callers decide whether to surface ``unavailable``.
        """
        from app.providers.litellm_adapter import LiteLLMModelAdapter

        target = registry or self._registry
        if target is None:
            from app.providers.model_profiles.service import default_model_registry

            target = default_model_registry()
        try:
            aliases = await self._client.list_models()
        except Exception:  # noqa: BLE001 - best-effort discovery (spec §36)
            return []
        newly: list[str] = []
        for alias in aliases:
            model_id = f"{LITELLM_LOGICAL_PREFIX}{alias}"
            if target.get_or_none(model_id) is not None:
                continue
            manifest = litellm_logical_manifest(alias)
            target.register(manifest, LiteLLMModelAdapter(manifest))
            newly.append(model_id)
        return newly
