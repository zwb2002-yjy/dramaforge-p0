"""Secret-free capability projection from existing manifests, without runtime I/O."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.providers.bootstrap import build_v3_registry
from app.providers.capabilities import Capability
from app.providers.capability_sources import (
    LifecycleWarning,
    OfficialSource,
    lifecycle_warnings,
    official_sources,
)
from app.providers.catalog_loader import ModelCatalogLoader, hash_manifest
from app.providers.catalog_publication import effective_publication_lifecycle
from app.providers.knowledge_projection import (
    ModelKnowledgeRead,
    knowledge_for_model,
    project_model_knowledge,
)
from app.providers.litellm_gateway.model_catalog import litellm_logical_manifest
from app.providers.manifest import (
    CapabilitySpec,
    InputModeSpec,
    ModelCapabilityManifest,
    ModelManifest,
    to_v3_model_manifest,
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
    knowledge: ModelKnowledgeRead | None = None


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
        catalog_lifecycle=effective_publication_lifecycle(
            catalog.provider_type, catalog.protocol_profile, catalog.model_id, catalog.lifecycle
        )
        if catalog
        else "unknown",
        capabilities={str(k): _public_spec(v) for k, v in manifest.capability_specs.items()},
        controls=controls,
        official_sources=official_sources(
            manifest.id, protocol_profile=catalog.protocol_profile if catalog else None
        ),
        lifecycle_warnings=lifecycle_warnings(manifest.id),
        limitations=limitations,
        knowledge=knowledge_for_model(
            catalog.provider_type, catalog.protocol_profile, catalog.model_id
        )
        if catalog
        else None,
    )


def inspect_catalog_model(
    model_id: str, *, registry: ModelRegistry | None = None
) -> ModelCapabilityReport:
    """Inspect a selected model; unknown IDs never fall back to another model."""
    matching = [
        item
        for item in ModelCatalogLoader().load()
        if f"{item.identity[0]}/{item.identity[2]}" == model_id
    ]
    typed = [item for item in matching if item.as_dict().get("schema_version") == "2"]
    matching = [item for item in matching if item.as_dict().get("schema_version", "1") == "1"]
    chosen = (
        max(matching, key=lambda item: (item.publication_lifecycle == "active", item.identity[3]))
        if matching
        else None
    )
    catalog_row = chosen.as_dict() if chosen is not None else None
    catalog = ModelCapabilityManifest.model_validate(catalog_row) if catalog_row else None
    if catalog is None and typed:
        candidate = max(typed, key=lambda item: item.identity[3])
        raw = candidate.as_dict()
        return ModelCapabilityReport(
            model_id=model_id,
            model_revision=candidate.identity[3],
            manifest_version=raw["manifest_version"],
            manifest_hash=candidate.manifest_hash,
            catalog_lifecycle=candidate.publication_lifecycle,
            capabilities={},
            controls={},
            knowledge=project_model_knowledge(raw),
            limitations=["Knowledge candidate; no executable Compiler."],
        )
    if registry is None:
        registry, _ = build_v3_registry()
        from app.config import get_settings

        if model_id in {f"litellm/{alias}" for alias in get_settings().litellm_logical_models}:
            return inspect_manifest(litellm_logical_manifest(model_id.removeprefix("litellm/")))
    selected = registry.get_or_none(model_id)
    if selected is None and catalog is not None:
        # Inspection of a frozen retired contract must remain possible. This
        # pure conversion neither registers a Runtime nor admits a new Create.
        from app.providers.bootstrap import transport_profile_id_for

        return inspect_manifest(
            to_v3_model_manifest(
                catalog,
                transport_profile_id=transport_profile_id_for(
                    catalog.provider_type, catalog.protocol_profile, catalog.media_kind
                )
                or "inspection-only",
            ),
            catalog=catalog,
            catalog_hash=chosen.manifest_hash if chosen else None,
        )
    if selected is None:
        raise NotFoundError("model not found")
    return inspect_manifest(
        selected.manifest,
        catalog=catalog,
        catalog_hash=hash_manifest(catalog_row) if catalog_row is not None else None,
    )
