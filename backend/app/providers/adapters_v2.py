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

from collections.abc import Callable
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
from app.providers.intent_bridge import request_to_intent
from app.providers.manifest import ModelCapabilityManifest, ModelManifest
from app.providers.runtime import (
    CompiledImageRequest,
    ProviderResumeToken,
    ProviderRuntime,
    ResolvedReference,
)
from app.providers.translation import EffectiveRequest, TranslationReport, TranslationResult

_SUBMISSION_STATUS_TO_V3 = {
    "succeeded": GenerationStatus.SUCCEEDED,
    "queued": GenerationStatus.SUBMITTED,
    "pending": GenerationStatus.SUBMITTED,
    "running": GenerationStatus.RUNNING,
    "failed": GenerationStatus.FAILED,
    "error": GenerationStatus.FAILED,
    "cancelled": GenerationStatus.CANCELLED,
    "unknown_submission": GenerationStatus.SUBMIT_UNKNOWN,
    "rejected": GenerationStatus.FAILED,
}


def submission_status_to_v3(status: str) -> GenerationStatus:
    return _SUBMISSION_STATUS_TO_V3.get(status, GenerationStatus.SUBMITTED)


ArtifactResolver = Callable[[list[tuple[str, ResolvedArtifact]]], list[ResolvedReference]]


def _uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"artifact id must be a UUID string, got: {value!r}") from exc


def _resolved_reference(role: str, artifact: ResolvedArtifact) -> ResolvedReference:
    """Map a V3 ResolvedArtifact to the A+B ResolvedReference. URL when a signed
    URL is available; bytes are supplied by the DB-bound create path."""
    return ResolvedReference(
        role=role,
        artifact_id=_uuid(artifact.artifact_id),
        content_url=artifact.signed_url,
        content_bytes=None,
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
        roles.append(("first_frame", slot(request.image.artifact_id, "image/*")))
    elif isinstance(request, FirstLastFrameVideoRequest):
        roles.append(("first_frame", slot(request.first_frame.artifact_id, "image/*")))
        roles.append(("last_frame", slot(request.last_frame.artifact_id, "image/*")))
    elif isinstance(request, ReferenceToVideoRequest):
        roles.extend(
            ("reference_image", ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="image/*"))
            for ref in request.reference_images
        )
        roles.extend(
            ("reference_audio", ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="audio/*"))
            for ref in request.reference_audio
        )
        roles.extend(
            ("reference_video", ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="video/*"))
            for ref in request.reference_videos
        )
    elif isinstance(request, ImageGenerateRequest):
        roles.extend(
            ("reference_image", ResolvedArtifact(artifact_id=ref.artifact_id, mime_type="image/*"))
            for ref in request.reference_images
        )
    return roles


class LegacyAdapterBridge:
    """V3 ModelAdapter facade over one A+B model's compiler+runtime.

    ``invoke_model_value`` is the wire ``model`` field (from the catalog
    binding). ``resolver`` (optional) resolves ArtifactRefs for the create path;
    without it, ``create`` refuses rather than guessing reference transport.
    """

    def __init__(
        self,
        v3_manifest: ModelManifest,
        components: BridgeComponents,
        *,
        invoke_model_value: str | None = None,
        resolver: ArtifactResolver | None = None,
    ) -> None:
        self._v3 = v3_manifest
        self._components = components
        self._invoke_model_value = invoke_model_value or v3_manifest.model_name
        self._resolver = resolver
        self._tokens: dict[str, ProviderResumeToken] = {}
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
        resolved_artifacts: dict[str, ResolvedArtifact],
    ) -> tuple[Any, TranslationResult]:
        intent = request_to_intent(capability, request)
        compiler = self._compiler_for(capability)
        a_b = self._components.a_b_manifest
        compiler.validate(intent, a_b)
        references = [
            _resolved_reference(role, artifact)
            for role, artifact in resolved_artifacts.items()
        ]
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
        translation = TranslationResult(
            capability=capability,
            effective_request=EffectiveRequest(
                capability=capability,
                model_id=self.model_id,
                inputs={"prompt": getattr(request, "prompt", "")},
                common_options=requested_options,
                native_options=dict(getattr(request, "native_options", {}) or {}),
            ),
            native_request=dict(getattr(compiled, "wire_request", {}) or {}),
            translation_report=TranslationReport(
                requested_options=requested_options,
                effective_options=requested_options,
            ),
        )
        return compiled, translation

    async def translate(
        self,
        capability: Capability,
        request: Any,
        resolved_artifacts: dict[str, ResolvedArtifact],
    ) -> TranslationResult:
        _, translation = await self._compile(capability, request, resolved_artifacts)
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
        resolved: dict[str, ResolvedArtifact] = {
            role: artifact for role, artifact in _request_reference_roles(request)
        }
        if resolved and self._resolver is not None:
            resolved_refs = self._resolver(list(resolved.items()))
            resolved = {
                ref.role: resolved[ref.role] for ref in resolved_refs if ref.role in resolved
            }
        compiled, _translation = await self._compile(capability, request, resolved)
        runtime = self._components.runtime
        if isinstance(compiled, CompiledImageRequest):
            result = await runtime.submit_image(compiled)
        else:
            result = await runtime.submit_video(compiled)
        if result.resume_token is not None and result.remote_task_id:
            self._tokens[result.remote_task_id] = result.resume_token
        return ProviderCreateResult(
            status=submission_status_to_v3(result.status),
            remote_task_id=result.remote_task_id,
            artifact_uri=result.artifact_uri,
            provider_metadata={
                "request_fingerprint": result.request_fingerprint,
                "request_summary": result.request_summary,
                "error_code": result.error_code,
            },
        )

    def _require_token(self, remote_task_id: str) -> ProviderResumeToken:
        token = self._tokens.get(remote_task_id)
        if token is None:
            raise RuntimeError(
                "no resume token for remote task; durable resume requires the "
                "persisted ProviderOperation resume_token"
            )
        return token

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
