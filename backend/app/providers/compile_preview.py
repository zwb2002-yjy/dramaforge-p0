"""Pure provider-contract preview; no Runtime, credentials, tokens or storage I/O.

Reference transports are placeholders. Success proves compiler acceptance, not
media validity, transport reachability, account access or executable readiness.
"""

from collections import Counter
from typing import Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.providers.catalog_loader import hash_manifest
from app.providers.intents import ImageGenerationIntent, VideoGenerationIntentV1
from app.providers.manifest import ModelCapabilityManifest
from app.providers.normalizer import normalize_image, normalize_video
from app.providers.reference_roles import ReferenceRoleValue
from app.providers.registry import get_plugin
from app.providers.runtime import ResolvedReference


class _PreviewIdentity(TypedDict):
    prompt_hash: str
    semantic_hash: str
    manifest_hash: str
    reference_ids: list[UUID]
    requested_options: dict[str, JsonValue]


class PreviewReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: ReferenceRoleValue
    artifact_id: UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: str = Field(pattern=r"^(image|video|audio)/[a-zA-Z0-9.+-]+$", max_length=100)


class CompilePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    compile_level: Literal["provider_contract"] = "provider_contract"
    readiness: Literal["contract_validated", "blocked"]
    transport_verified: Literal[False] = False
    account_verified: Literal[False] = False
    prompt_hash: str
    semantic_hash: str
    manifest_hash: str
    reference_ids: list[UUID]
    requested_options: dict[str, JsonValue] = Field(default_factory=dict)
    effective_options: dict[str, JsonValue] = Field(default_factory=dict)
    transformations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=lambda: [
            "PLACEHOLDER_TRANSPORT_NOT_VERIFIED",
            "MEDIA_BYTES_NOT_VERIFIED",
            "ACCOUNT_NOT_CHECKED",
        ]
    )


def _reference_errors(
    intent: ImageGenerationIntent | VideoGenerationIntentV1,
    manifest: ModelCapabilityManifest,
    references: list[PreviewReference],
) -> list[str]:
    expected = (
        [("reference_image", reference_id) for reference_id in intent.selected_reference_ids()]
        if isinstance(intent, ImageGenerationIntent)
        else [(r.role, r.artifact_id) for r in intent.references]
    )
    if expected != [(r.role, r.artifact_id) for r in references]:
        return ["REFERENCE_IDENTITY_MISMATCH"]
    operation = manifest.operations.get(intent.operation)
    if operation is None:
        return ["OPERATION_UNSUPPORTED"]
    from app.providers.capabilities import Capability
    from app.providers.manifest import to_v3_model_manifest

    capability = (
        Capability.IMAGE_GENERATE
        if isinstance(intent, ImageGenerationIntent)
        else Capability.VIDEO_IMAGE_TO_VIDEO
    )
    spec = to_v3_model_manifest(manifest, transport_profile_id="preview").capability_specs.get(
        capability
    )
    counts: Counter[str] = Counter(ref.role for ref in references)
    if spec is not None and spec.modes:
        try:
            mode = spec.mode_spec(intent.mode_id)
        except ValueError:
            return ["MODE_UNSUPPORTED"]
        if any(role not in mode.input_slots for role in counts):
            return ["MODE_REFERENCE_UNSUPPORTED"]
        for role, slot in mode.input_slots.items():
            count = counts.get(role, 0)
            if count < (slot.minimum or (1 if slot.required else 0)) or (
                slot.maximum is not None and count > slot.maximum
            ):
                return ["MODE_REFERENCE_UNSUPPORTED"]
    else:
        for role, count in counts.items():
            constraint = operation.reference_constraints.get(role)
            if constraint is None or count > constraint.max:
                return ["REFERENCE_SLOT_UNSUPPORTED"]
        if any(
            counts.get(role, 0) < constraint.min
            for role, constraint in operation.reference_constraints.items()
        ):
            return ["REFERENCE_REQUIRED"]
    if isinstance(intent, ImageGenerationIntent) and references:
        ref = references[0]
        if (intent.reference_fingerprint and intent.reference_fingerprint != ref.fingerprint) or (
            intent.reference_mime and intent.reference_mime != ref.mime_type
        ):
            return ["REFERENCE_IDENTITY_MISMATCH"]
    if any(
        not ref.mime_type.startswith(
            "audio/"
            if ref.role == "reference_audio"
            else "video/"
            if ref.role == "reference_video"
            else "image/"
        )
        for ref in references
    ):
        return ["REFERENCE_MEDIA_UNSUPPORTED"]
    return []


def _effective_options(wire: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Only compiler-controlled scalar fields; never prompt/reference/raw payload."""
    allowed = {
        "size",
        "ratio",
        "aspect_ratio",
        "duration",
        "resolution",
        "seed",
        "width",
        "height",
        "num_frames",
        "frame_rate",
        "generate_audio",
        "n",
        "watermark",
        "aigc_watermark",
        "prompt_optimizer",
    }
    return {
        (
            "aspect_ratio" if key == "ratio" else "duration_seconds" if key == "duration" else key
        ): value
        for key, value in wire.items()
        if key in allowed and isinstance(value, (str, int, float, bool))
    }


async def preview_compile(
    *,
    manifest: ModelCapabilityManifest,
    invoke_model_value: str,
    intent: ImageGenerationIntent | VideoGenerationIntentV1,
    references: list[PreviewReference],
) -> CompilePreview:
    import hashlib

    requested: dict[str, JsonValue] = (
        {"size": intent.size, "aspect_ratio": intent.aspect_ratio, "seed": intent.seed}
        if isinstance(intent, ImageGenerationIntent)
        else intent.output.model_dump(mode="json")
    )
    common: _PreviewIdentity = {
        "prompt_hash": hashlib.sha256(intent.prompt.encode()).hexdigest(),
        "semantic_hash": hash_manifest(
            {
                "intent": intent.model_dump(mode="json"),
                "model": invoke_model_value,
                "manifest": manifest.model_dump(mode="json"),
                "references": [ref.model_dump(mode="json") for ref in references],
            }
        ),
        "manifest_hash": hash_manifest(manifest.model_dump(mode="json")),
        "reference_ids": [ref.artifact_id for ref in references],
        "requested_options": requested,
    }
    errors = _reference_errors(intent, manifest, references)
    from app.providers.capabilities import Capability
    from app.providers.manifest import to_v3_model_manifest

    capability = (
        Capability.IMAGE_GENERATE
        if isinstance(intent, ImageGenerationIntent)
        else Capability.VIDEO_IMAGE_TO_VIDEO
    )
    spec = to_v3_model_manifest(manifest, transport_profile_id="preview").capability_specs.get(
        capability
    )
    if spec is not None:
        if spec.modes:
            try:
                spec.mode_spec(intent.mode_id)
            except ValueError:
                errors.append("MODE_UNSUPPORTED")
        else:
            # Legacy catalogs expose slots without named modes. Workbench still
            # freezes its image/first-frame stage name; validate that name here
            # while the reference and compiler checks retain the actual contract.
            workbench_mode = (
                "text_to_image" if isinstance(intent, ImageGenerationIntent) else "first_frame"
            )
            if intent.mode_id not in {None, "default", "explicit_binding", workbench_mode}:
                errors.append("MODE_UNSUPPORTED")
    if not invoke_model_value.strip():
        errors.append("MODEL_IDENTITY_MISSING")
    normalized = (
        normalize_image(intent)
        if isinstance(intent, ImageGenerationIntent)
        else normalize_video(intent)
    )
    operation = manifest.operations.get(intent.operation)
    if normalized.errors:
        errors.append("INTENT_UNSUPPORTED")
    if operation and not normalized.required_capabilities.issubset(set(operation.capabilities)):
        errors.append("CAPABILITY_UNSUPPORTED")
    if errors:
        return CompilePreview(readiness="blocked", errors=sorted(set(errors)), **common)
    try:
        plugin = get_plugin(manifest.provider_type, manifest.protocol_profile)
        if not plugin.implemented or plugin.compiler_factory is None:
            return CompilePreview(readiness="blocked", errors=["COMPILER_UNAVAILABLE"], **common)
        image_compiler, video_compiler = plugin.compiler_factory()
        compiler = image_compiler if isinstance(intent, ImageGenerationIntent) else video_compiler
        # Use the selected compiler contract, never the probe transport or
        # provider-name heuristics. No reference bytes are loaded here.
        transport = getattr(compiler, "reference_transport", None)
        if transport not in {"bytes", "public_url"}:
            return CompilePreview(
                readiness="blocked", errors=["REFERENCE_TRANSPORT_UNDECLARED"], **common
            )
        as_bytes = transport == "bytes"
        resolved = [
            ResolvedReference(
                role=ref.role,
                artifact_id=ref.artifact_id,
                mime_type=ref.mime_type,
                fingerprint=ref.fingerprint,
                content_bytes=b"preview-placeholder" if as_bytes else None,
                content_url=None if as_bytes else f"https://preview.invalid/{ref.artifact_id}",
            )
            for ref in references
        ]
        compiled = await compiler.compile(
            intent,
            manifest,
            resolved,
            invoke_model_value=invoke_model_value,
        )
        if compiled.reference_artifact_ids != [ref.artifact_id for ref in references]:
            return CompilePreview(
                readiness="blocked", errors=["REFERENCE_IDENTITY_MISMATCH"], **common
            )
        effective = _effective_options(compiled.wire_request)
        transformations = [
            f"{key}:compiler_mapped"
            for key, value in requested.items()
            if value is not None and effective.get(key) != value
        ]
        return CompilePreview(
            readiness="contract_validated",
            effective_options=effective,
            transformations=transformations,
            **common,
        )
    except (ValueError, LookupError):
        # Compiler exceptions may include caller-controlled text; only a stable
        # code leaves this boundary. The original prompt/wire never leaves it.
        return CompilePreview(
            readiness="blocked", errors=["PROVIDER_CONTRACT_UNSUPPORTED"], **common
        )
