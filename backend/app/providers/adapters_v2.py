"""V3 ModelAdapter V2 implementations and the legacy bridge (spec §26–§27).

A :class:`LegacyAdapterBridge` presents the existing A+B Compiler/Runtime pair
behind the V3 :class:`ModelAdapter` surface. ``translate()`` is pure and
unit-testable without a provider; ``create()``/``poll()``/``cancel()``/
``fetch_cost()`` delegate to the wrapped runtime when it is wired.

LEGACY_COMPAT: the A+B intents and CompiledRequest objects are only touched
inside this bridge. Business code above the CapabilityRouter never sees them.
Remove this bridge (and the direct HubClient dict adapters) when the unified
CapabilityRouter path fully owns submission (Phase 11/12).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.providers.capabilities import Capability
from app.providers.contracts.common import (
    ExecutionContext,
    GenerationStatus,
    ProviderCancelResult,
    ProviderCostResult,
    ProviderCreateResult,
    ProviderPollResult,
    ResolvedArtifact,
)
from app.providers.contracts.image import ImageGenerateRequest
from app.providers.contracts.video import (
    FirstLastFrameVideoRequest,
    ImageToVideoRequest,
    ReferenceToVideoRequest,
)
from app.providers.errors import ProviderStateMappingError, ResumeTokenUnavailableError
from app.providers.intent_bridge import request_to_intent
from app.providers.manifest import ModelCapabilityManifest, ModelManifest
from app.providers.reference_roles import ReferenceRole
from app.providers.runtime import (
    CompiledImageRequest,
    ProviderResumeToken,
    ProviderRuntime,
    ResolvedReference,
)
from app.providers.translation import (
    EffectiveRequest,
    RequestTransformation,
    TranslationReport,
    TranslationResult,
)

_SUBMISSION_STATUS_TO_V3 = {
    "succeeded": GenerationStatus.SUCCEEDED,
    "completed": GenerationStatus.SUCCEEDED,
    "success": GenerationStatus.SUCCEEDED,
    "done": GenerationStatus.SUCCEEDED,
    "queued": GenerationStatus.SUBMITTED,
    "pending": GenerationStatus.SUBMITTED,
    "processing": GenerationStatus.SUBMITTED,
    "submitted": GenerationStatus.SUBMITTED,
    "running": GenerationStatus.RUNNING,
    "progress": GenerationStatus.RUNNING,
    "failed": GenerationStatus.FAILED,
    "error": GenerationStatus.FAILED,
    "rejected": GenerationStatus.FAILED,
    "expired": GenerationStatus.FAILED,
    "cancelled": GenerationStatus.CANCELLED,
    "canceled": GenerationStatus.CANCELLED,
    "unknown_submission": GenerationStatus.SUBMIT_UNKNOWN,
}


def submission_status_to_v3(status: str) -> GenerationStatus:
    """Explicit status mapping (HIGH-1 / spec invariant 5). An unmapped provider
    status is an explicit error, never a silent default to SUBMITTED — a missing
    mapping could otherwise hide a terminal provider state behind a poll loop."""
    try:
        return _SUBMISSION_STATUS_TO_V3[status]
    except KeyError as exc:
        raise ProviderStateMappingError(status) from exc


ArtifactResolver = Callable[[list[tuple[str, ResolvedArtifact]]], list[ResolvedReference]]
ReferenceInput = Mapping[str, ResolvedArtifact] | Sequence[ResolvedReference]

_COMPILER_AUDIT_OPTION_FIELDS = frozenset(
    {"aspect_ratio", "duration_seconds", "resolution", "generate_audio", "seed", "size"}
)
_COMPILER_AUDIT_REASON_CODES = frozenset(
    {
        "provider_inherits_aspect_ratio_from_first_frame",
        "provider_applies_documented_default",
        "frozen_manifest_native_size_tier",
    }
)


def _compiler_translation_evidence(
    compiled: object,
) -> tuple[dict[str, Any] | None, list[RequestTransformation]]:
    """Read a deliberately small, secret-free compiler audit envelope.

    Existing compilers which do not publish the envelope retain their current
    translation behavior.  A compiler which does publish it must conform to
    this allowlisted scalar schema; malformed or unexpected data fails closed.
    """
    summary = getattr(compiled, "safe_request_summary", None)
    if not isinstance(summary, dict):
        return None, []
    has_effective = "effective_common_options" in summary
    has_transformations = "translation_transformations" in summary
    if not has_effective and not has_transformations:
        return None, []
    if not has_effective or not has_transformations:
        raise ValueError("compiler translation evidence is incomplete")

    raw_effective = summary["effective_common_options"]
    raw_transformations = summary["translation_transformations"]
    if not isinstance(raw_effective, dict) or not isinstance(raw_transformations, list):
        raise ValueError("compiler translation evidence has an invalid schema")

    def safe_value(field: str, value: object) -> bool:
        if value is None:
            return True
        if field in {"aspect_ratio", "resolution", "size"}:
            return isinstance(value, str) and 0 < len(value) <= 32
        if field == "duration_seconds":
            return (
                not isinstance(value, bool)
                and isinstance(value, int | float)
                and math.isfinite(value)
                and 0 < value <= 3600
            )
        if field == "generate_audio":
            return isinstance(value, bool)
        if field == "seed":
            return (
                not isinstance(value, bool)
                and isinstance(value, int)
                and -(2**63) <= value < 2**63
            )
        return False

    effective: dict[str, Any] = {}
    for key, value in raw_effective.items():
        if (
            not isinstance(key, str)
            or key not in _COMPILER_AUDIT_OPTION_FIELDS
            or not safe_value(key, value)
        ):
            raise ValueError("compiler effective options are not safe common options")
        effective[key] = value

    transformations: list[RequestTransformation] = []
    for raw in raw_transformations:
        if not isinstance(raw, dict) or set(raw) != {
            "field",
            "from_value",
            "to_value",
            "reason",
        }:
            raise ValueError("compiler transformation has an invalid schema")
        field = raw["field"]
        reason = raw["reason"]
        if (
            not isinstance(field, str)
            or field not in _COMPILER_AUDIT_OPTION_FIELDS
            or not isinstance(reason, str)
            or reason not in _COMPILER_AUDIT_REASON_CODES
            or not safe_value(field, raw["from_value"])
            or not safe_value(field, raw["to_value"])
        ):
            raise ValueError("compiler transformation is not safe audit evidence")
        transformations.append(RequestTransformation.model_validate(raw))
    return effective, transformations


def _uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"artifact id must be a UUID string, got: {value!r}") from exc


def _resolved_reference(role: str, artifact: ResolvedArtifact) -> ResolvedReference:
    """Map a V3 ResolvedArtifact to the A+B ResolvedReference. URL and/or bytes
    are passed through from the resolver (BLOCK-4): the compiler decides the
    transport (Ark uses the URL, Agnes uses the bytes)."""
    return ResolvedReference(
        role=role,
        artifact_id=_uuid(artifact.artifact_id),
        content_url=artifact.signed_url,
        content_bytes=artifact.content_bytes,
        mime_type=artifact.mime_type,
        fingerprint=artifact.sha256,
    )


@dataclass(frozen=True)
class BridgeComponents:
    """The A+B pieces a bridge wraps: capability manifest, compilers, runtime."""

    a_b_manifest: ModelCapabilityManifest
    image_compiler: Any | None
    video_compiler: Any | None
    runtime: ProviderRuntime | None


def _request_reference_roles(request: Any) -> list[tuple[str, ResolvedArtifact]]:
    """Collect (role, artifact) pairs the request references, in role order."""

    def slot(artifact_id: str, mime_type: str) -> ResolvedArtifact:
        return ResolvedArtifact(artifact_id=artifact_id, mime_type=mime_type)

    roles: list[tuple[str, ResolvedArtifact]] = []
    if isinstance(request, ImageToVideoRequest):
        roles.append(
            (ReferenceRole.FIRST_FRAME.value, slot(request.image.artifact_id, "image/*"))
        )
    elif isinstance(request, FirstLastFrameVideoRequest):
        roles.append(
            (ReferenceRole.FIRST_FRAME.value, slot(request.first_frame.artifact_id, "image/*"))
        )
        roles.append(
            (ReferenceRole.LAST_FRAME.value, slot(request.last_frame.artifact_id, "image/*"))
        )
    elif isinstance(request, ReferenceToVideoRequest):
        roles.extend(
            (
                ReferenceRole.REFERENCE_IMAGE.value,
                ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="image/*"),
            )
            for ref in request.reference_images
        )
        roles.extend(
            (
                ReferenceRole.REFERENCE_AUDIO.value,
                ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="audio/*"),
            )
            for ref in request.reference_audio
        )
        roles.extend(
            (
                ReferenceRole.REFERENCE_VIDEO.value,
                ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="video/*"),
            )
            for ref in request.reference_videos
        )
    elif isinstance(request, ImageGenerateRequest):
        roles.extend(
            (
                ReferenceRole.REFERENCE_IMAGE.value,
                ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="image/*"),
            )
            for ref in request.reference_images
        )
    return roles


class LegacyAdapterBridge:
    """V3 ModelAdapter facade over one A+B model's compiler+runtime.

    ``invoke_model_value`` is the wire ``model`` field (from the catalog
    binding). ``resolver`` (optional) resolves ArtifactRefs for the create path
    and its :class:`ResolvedReference` output (URL/bytes/fingerprint) is what
    the compiler receives; without it, a reference-bearing create refuses rather
    than guessing reference transport.

    Durable lifecycle: ``create`` returns the provider resume token in
    ``provider_metadata`` for the Operation Service to persist on
    ``ProviderOperation.resume_token``. ``poll``/``cancel``/``fetch_cost`` read
    the token from ``token_provider`` (or raise
    :class:`ResumeTokenUnavailableError`) — they never depend on process-local
    memory, so a restart or another worker can resume the same remote task.
    """

    def __init__(
        self,
        v3_manifest: ModelManifest,
        components: BridgeComponents,
        *,
        invoke_model_value: str | None = None,
        resolver: ArtifactResolver | None = None,
        token_provider: Callable[[str], ProviderResumeToken | None] | None = None,
    ) -> None:
        self._v3 = v3_manifest
        self._components = components
        self._invoke_model_value = invoke_model_value or v3_manifest.model_name
        self._resolver = resolver
        self._token_provider = token_provider
        self.provider_id = v3_manifest.provider_id
        self.model_id = v3_manifest.id

    @property
    def manifest(self) -> ModelManifest:
        return self._v3

    @property
    def protocol_profile(self) -> str:
        raw = self._v3.metadata.get("protocol_profile")
        return str(raw) if raw else ""

    def _compiler_for(self, capability: Capability) -> Any:
        if capability in {Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT}:
            if self._components.image_compiler is None:
                raise RuntimeError("model has no image compiler")
            return self._components.image_compiler
        if self._components.video_compiler is None:
            raise RuntimeError("model has no video compiler")
        return self._components.video_compiler

    async def _compile(
        self,
        capability: Capability,
        request: Any,
        resolved_references: list[ResolvedReference],
    ) -> tuple[Any, TranslationResult]:
        intent = request_to_intent(capability, request)
        compiler = self._compiler_for(capability)
        a_b = self._components.a_b_manifest
        compiler.validate(intent, a_b)
        references = list(resolved_references)
        compiled = await compiler.compile(
            intent,
            a_b,
            references,
            invoke_model_value=self._invoke_model_value,
        )
        requested_options: dict[str, Any] = {}
        if isinstance(request, BaseModel):
            requested_options = request.model_dump(
                exclude={
                    "prompt",
                    "native_options",
                    "image",
                    "first_frame",
                    "last_frame",
                    "reference_images",
                    "reference_audio",
                    "reference_videos",
                }
            )
        compiler_effective, compiler_transformations = _compiler_translation_evidence(compiled)
        effective_options = (
            compiler_effective if compiler_effective is not None else requested_options
        )
        translation = TranslationResult(
            capability=capability,
            effective_request=EffectiveRequest(
                capability=capability,
                model_id=self.model_id,
                inputs={"prompt": getattr(request, "prompt", "")},
                common_options=effective_options,
                native_options=dict(getattr(request, "native_options", {}) or {}),
            ),
            native_request=dict(getattr(compiled, "wire_request", {}) or {}),
            translation_report=TranslationReport(
                requested_options=requested_options,
                effective_options=effective_options,
                transformations=compiler_transformations,
            ),
        )
        return compiled, translation

    @staticmethod
    def _coerce_reference_input(resolved_artifacts: ReferenceInput) -> list[ResolvedReference]:
        """Convert the legacy mapping surface without reintroducing role dedupe.

        A mapping is retained only for old callers and therefore cannot recover
        duplicates that were already collapsed by that caller. New callers use
        ``translate_v2`` and pass the ordered ``ResolvedReference`` list directly.
        """
        if isinstance(resolved_artifacts, Mapping):
            return [
                _resolved_reference(role, artifact)
                for role, artifact in resolved_artifacts.items()
            ]
        return list(resolved_artifacts)

    async def translate(
        self,
        capability: Capability,
        request: Any,
        resolved_artifacts: ReferenceInput,
    ) -> TranslationResult:
        """Compatibility surface for old mapping callers and ordered V2 input."""
        _, translation = await self._compile(
            capability,
            request,
            self._coerce_reference_input(resolved_artifacts),
        )
        return translation

    async def translate_v2(
        self,
        capability: Capability,
        request: Any,
        resolved_references: list[ResolvedReference],
    ) -> TranslationResult:
        """Translate an ordered reference list without a role-keyed intermediary."""
        _, translation = await self._compile(capability, request, list(resolved_references))
        return translation

    async def create(
        self,
        capability: Capability,
        request: Any,
        context: ExecutionContext,
    ) -> ProviderCreateResult:
        if self._components.runtime is None:
            raise RuntimeError(
                "bridge has no runtime; use the DB-bound submission path "
                "(Phase 5/6)"
            )
        requested_references = _request_reference_roles(request)
        if requested_references and self._resolver is not None:
            # BLOCK-4/MS3: resolver output stays an ordered list all the way to
            # the compiler. Never rebuild it through dict[role, artifact].
            resolved_references = list(self._resolver(requested_references))
        else:
            resolved_references = [
                _resolved_reference(role, artifact)
                for role, artifact in requested_references
            ]
        compiled, _translation = await self._compile(
            capability,
            request,
            resolved_references,
        )
        runtime = self._components.runtime
        if isinstance(compiled, CompiledImageRequest):
            result = await runtime.submit_image(compiled)
        else:
            result = await runtime.submit_video(compiled)
        metadata: dict[str, Any] = {
            "request_fingerprint": result.request_fingerprint,
            "request_summary": result.request_summary,
            "error_code": result.error_code,
        }
        if result.resume_token is not None:
            # The Operation Service persists this on ProviderOperation.resume_token
            # so a later poll on any process can resume (HIGH-2).
            metadata["resume_token"] = result.resume_token.model_dump(mode="json")
        return ProviderCreateResult(
            status=submission_status_to_v3(result.status),
            remote_task_id=result.remote_task_id,
            artifact_uri=result.artifact_uri,
            provider_metadata=metadata,
        )

    def _require_token(self, remote_task_id: str) -> ProviderResumeToken:
        if self._token_provider is not None:
            token = self._token_provider(remote_task_id)
            if token is not None:
                return token
        raise ResumeTokenUnavailableError(remote_task_id)

    async def poll(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderPollResult:
        if self._components.runtime is None:
            raise RuntimeError("bridge has no runtime")
        poll = await self._components.runtime.poll_video(self._require_token(remote_task_id))
        return ProviderPollResult(
            status=submission_status_to_v3(poll.status),
            progress=poll.progress,
            artifact_uri=poll.artifact_uri,
            error_code=poll.error_code,
            provider_metadata={"http_status": poll.http_status},
        )

    async def cancel(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCancelResult:
        if self._components.runtime is None:
            raise RuntimeError("bridge has no runtime")
        result = await self._components.runtime.cancel_video(self._require_token(remote_task_id))
        return ProviderCancelResult(
            status=submission_status_to_v3(result.status),
            accepted=True,
        )

    async def fetch_cost(
        self,
        remote_task_id: str,
        context: ExecutionContext,
    ) -> ProviderCostResult:
        if self._components.runtime is None:
            raise RuntimeError("bridge has no runtime")
        result = await self._components.runtime.fetch_cost(self._require_token(remote_task_id))
        return ProviderCostResult(
            currency=result.currency or "USD",
            amount=_decimal_or_none(result.amount),
        )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return None
