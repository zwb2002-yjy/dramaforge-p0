"""Pure provider-contract preview; no Runtime, credentials, tokens or storage I/O.

Reference transports are placeholders. Success proves compiler acceptance, not
media validity, transport reachability, account access or executable readiness.
"""

import base64
import hashlib
import json
import re
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
from app.providers.runtime import (
    CompiledImageRequest,
    CompiledVideoRequest,
    ResolvedReference,
)
from app.providers.workbench_contract import select_workbench_contract


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
    wire_fingerprint: str | None = None
    redacted_wire: dict[str, JsonValue] = Field(default_factory=dict)
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


def compiled_wire_evidence(
    compiled: CompiledImageRequest | CompiledVideoRequest,
    references: list[ResolvedReference],
) -> tuple[str, dict[str, JsonValue]]:
    """Exact non-media wire fields + ordered frozen reference identities.

    Random reference grants and raw media bytes are replaced with typed slot
    markers, so preflight and Worker can compare the actual Compiler output
    without disclosing the URL token, image bytes or credentials.
    """
    replacements: list[tuple[str, str]] = []
    for index, ref in enumerate(references):
        marker = f"<reference:{index}:{ref.fingerprint or ref.artifact_id}>"
        if ref.content_url:
            replacements.append((ref.content_url, marker))
        if ref.content_bytes:
            replacements.append((base64.b64encode(ref.content_bytes).decode("ascii"), marker))
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)

    def scrub(value: JsonValue, key: str = "") -> JsonValue:
        if isinstance(value, dict):
            result: dict[str, JsonValue] = {}
            for field, child in value.items():
                normalized = field.lower().replace("-", "_")
                if any(
                    fragment in normalized
                    for fragment in (
                        "authorization",
                        "api_key",
                        "apikey",
                        "password",
                        "secret",
                        "ciphertext",
                        "bearer",
                    )
                ):
                    raise ValueError("credential key in Provider wire")
                result[field] = scrub(child, field)
            return result
        if isinstance(value, list):
            return [scrub(child, key) for child in value]
        if isinstance(value, str):
            result = value
            for raw, marker in replacements:
                if raw in result:
                    result = result.replace(raw, marker)
            # A byte-backed adapter may wrap the exact resolved bytes as a
            # data URI. Strip that entire envelope after replacing its payload,
            # so placeholder bytes and verified Worker bytes hash identically.
            # Never retain raw or unrelated inline base64 in the projection.
            data_uri = re.fullmatch(
                r"data:[a-zA-Z0-9.+/-]+;base64,(<reference:[^>]+>)",
                result,
            )
            if data_uri is not None:
                result = data_uri.group(1)
            if "https://" in result or "http://" in result or ";base64," in result:
                raise ValueError("unbound URL or media value in Provider wire")
            if ("base64" in key.lower() or "b64" in key.lower()) and "<reference:" not in result:
                raise ValueError("unbound binary field in Provider wire")
            return result
        return value

    projection: dict[str, JsonValue] = {
        "provider_type": compiled.provider_type,
        "protocol_profile": compiled.protocol_profile,
        "model_id": compiled.model_id,
        "operation": compiled.operation,
        "request_schema_version": compiled.request_schema_version,
        "wire_request": scrub(compiled.wire_request),
        "reference_artifact_ids": [str(value) for value in compiled.reference_artifact_ids],
        # Binary preview fixtures do not contain the media bytes. The actual
        # Worker validates storage SHA-256 before compiling. The proof always
        # binds the frozen reference hashes, never fixture-byte digests.
        "reference_fingerprints": [ref.fingerprint for ref in references],
    }
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), projection


async def preview_compile(
    *,
    manifest: ModelCapabilityManifest,
    invoke_model_value: str,
    intent: ImageGenerationIntent | VideoGenerationIntentV1,
    references: list[PreviewReference],
    expected_mode_id: str | None = None,
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
        if operation is not None and operation.input_contracts:
            selected = select_workbench_contract(
                operation=operation,
                media_kind="image" if isinstance(intent, ImageGenerationIntent) else "video",
                references=[(ref.role, ref.mime_type) for ref in resolved],
            )
            if expected_mode_id is not None and selected.contract_id != expected_mode_id:
                return CompilePreview(
                    readiness="blocked", errors=["CONTRACT_MODE_MISMATCH"], **common
                )
            if isinstance(intent, VideoGenerationIntentV1):
                intent = intent.model_copy(
                    update={"output": intent.output.model_copy(update={"generate_audio": None})}
                )
            from typing import Any, cast

            compiled = await cast(Any, compiler).compile(
                intent,
                manifest,
                resolved,
                invoke_model_value=invoke_model_value,
                policy=selected.policy,
            )
        else:
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
        fingerprint, redacted_wire = compiled_wire_evidence(compiled, resolved)
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
            wire_fingerprint=fingerprint,
            redacted_wire=redacted_wire,
            **common,
        )
    except (ValueError, LookupError, TypeError):
        # Compiler exceptions may include caller-controlled text; only a stable
        # code leaves this boundary. The original prompt/wire never leaves it.
        return CompilePreview(
            readiness="blocked", errors=["PROVIDER_CONTRACT_UNSUPPORTED"], **common
        )
