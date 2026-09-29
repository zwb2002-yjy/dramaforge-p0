"""Secret-free capability projection from existing manifests, without runtime I/O."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.providers.bootstrap import build_v3_registry, litellm_text_manifest
from app.providers.capabilities import Capability
from app.providers.capability_sources import (
    LifecycleWarning,
    OfficialSource,
    lifecycle_warnings,
    official_sources,
)
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
from app.providers.manifest import (
    CapabilitySpec,
    InputModeSpec,
    ModelCapabilityManifest,
    ModelManifest,
)
from app.providers.registry import ModelRegistry
from app.shared.errors import NotFoundError


class ModelCapabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    model_id: str
    model_revision: str | None = None
    manifest_version: str
    manifest_hash: str
    catalog_lifecycle: str
    capabilities: dict[str, CapabilitySpec]
    controls: dict[str, Literal["native", "prompt_only", "unsupported", "unknown"]]
    account_status: Literal["not_checked"] = "not_checked"
    official_sources: list[OfficialSource] = Field(default_factory=list)
    lifecycle_warnings: list[LifecycleWarning] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _public_spec(spec: CapabilitySpec) -> CapabilitySpec:
    public = spec.model_copy(deep=True)
    surfaces: list[CapabilitySpec | InputModeSpec] = [public, *public.modes.values()]
    for surface in surfaces:
        for options in (surface.common_options, surface.native_options):
            for name, parameter in options.items():
                if parameter.sensitive:
                    options[name] = parameter.model_copy(
                        update={
                            "default": None,
                            "enum": None,
                            "title": None,
                            "description": None,
                        }
                    )
    return public


def inspect_manifest(
    manifest: ModelManifest,
    *,
    catalog: ModelCapabilityManifest | None = None,
    catalog_hash: str | None = None,
) -> ModelCapabilityReport:
    """Project only the public contract, never arbitrary manifest metadata."""
    if catalog is not None and catalog_hash is None:
        raise ValueError("catalog inspection requires the original manifest hash")
    media = any(cap != Capability.TEXT_GENERATE for cap in manifest.capability_specs)
    options = {name for spec in manifest.capability_specs.values() for name in spec.common_options}
    controls: dict[str, Literal["native", "prompt_only", "unsupported", "unknown"]] = {
        "camera_motion": "native"
        if "camera_motion" in options
        else "prompt_only"
        if media
        else "unsupported",
        "style": "prompt_only",
        "native_audio": "native" if "generate_audio" in options else "unsupported",
        "tool_calling": "unsupported" if media else "unknown",
        "structured_output": "unsupported" if media else "unknown",
    }
    limitations = ["Contract inspection does not verify account access or generation quality."]
    if catalog is not None:
        limitations.append(
            "Declared output constraints are not all writable wire parameters; use compile preview."
        )
        if not any(spec.modes for spec in manifest.capability_specs.values()):
            limitations.append(
                "No explicit InputModeSpec is declared; "
                "legacy/explicit_binding uses declared slots."
            )
    if not media:
        limitations += [
            "Logical gateway aliases do not identify an immutable upstream deployment.",
            "Tool request forwarding is not a complete tool-result conversation contract.",
        ]
    return ModelCapabilityReport(
        model_id=manifest.id,
        model_revision=catalog.model_revision if catalog else None,
        manifest_version=manifest.manifest_version,
        manifest_hash=catalog_hash
        or hash_manifest(
            {
                "id": manifest.id,
                "manifest_version": manifest.manifest_version,
                "capability_specs": {
                    str(k): v.model_dump(mode="json") for k, v in manifest.capability_specs.items()
                },
            }
        ),
        catalog_lifecycle=catalog.lifecycle if catalog else "unknown",
        capabilities={str(k): _public_spec(v) for k, v in manifest.capability_specs.items()},
        controls=controls,
        official_sources=official_sources(manifest.id),
        lifecycle_warnings=lifecycle_warnings(manifest.id),
        limitations=limitations,
    )


def inspect_catalog_model(
    model_id: str, *, registry: ModelRegistry | None = None
) -> ModelCapabilityReport:
    """Inspect a selected model; unknown IDs never fall back to another model."""
    catalog_row = next(
        (
            row for row in SEED_MANIFESTS
            if f"{row['provider_type']}/{row['model_id']}" == model_id
        ),
        None,
    )
    catalog = ModelCapabilityManifest.model_validate(catalog_row) if catalog_row else None
    from app.providers.local_tts import LocalEspeakAdapter

    if model_id == f"{LocalEspeakAdapter.provider}/{LocalEspeakAdapter.model}":
        spec = CapabilitySpec(capability=Capability.AUDIO_TTS, transport_profile_id="local-process")
        return ModelCapabilityReport(
            model_id=model_id,
            manifest_version="local-espeak-contract-v1",
            manifest_hash=hash_manifest({"model": model_id, "output": "audio/wav"}),
            catalog_lifecycle="local_runtime",
            capabilities={str(Capability.AUDIO_TTS): spec},
            controls={
                "camera_motion": "unsupported",
                "style": "unsupported",
                "tool_calling": "unsupported",
                "native_audio": "native",
            },
            limitations=[
                "Local executable availability is not checked; no process was started.",
                "Voice and engine are deployment configuration, not request options.",
            ],
        )
    if model_id == "litellm/text-llm":
        return inspect_manifest(litellm_text_manifest())
    if registry is None:
        registry, _ = build_v3_registry()
        from app.config import get_settings

        if model_id in {f"litellm/{alias}" for alias in get_settings().litellm_logical_models}:
            return inspect_manifest(litellm_logical_manifest(model_id.removeprefix("litellm/")))
    selected = registry.get_or_none(model_id)
    if selected is None:
        raise NotFoundError("model not found")
    return inspect_manifest(
        selected.manifest,
        catalog=catalog,
        catalog_hash=hash_manifest(catalog_row) if catalog_row is not None else None,
    )
