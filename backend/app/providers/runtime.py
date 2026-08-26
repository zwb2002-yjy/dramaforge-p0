"""Unified Provider runtime/compiler contracts and resolver (stage B).

Single wire owner: a Compiler produces ``CompiledVideoRequest.wire_request`` and
the Runtime ``submit_*`` sends it verbatim. Existing HubClient methods become
compatible wrappers over the same low-level transport. Resume is driven by a
sanitized :class:`ProviderResumeToken` persisted on ``ProviderOperation`` —
never by current Feature Flags or the current Project binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator

from app.providers.catalog_models import ModelCatalogEntry
from app.providers.intents import (
    ImageGenerationIntent,
    VideoGenerationIntentV1,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.providers.registry import ProviderPlugin
from app.shared.errors import NotFoundError, ValidationAppError


class ProviderResumeToken(BaseModel):
    """Sanitized resume context. Never carries secrets, raw media, short-lived
    URLs, or a full unredacted wire body."""

    provider_type: str
    protocol_profile: str
    remote_task_id: str
    remote_secondary_id: str | None = None
    query_kind: str | None = None
    opaque_state: dict[str, JsonValue] = Field(default_factory=dict)


class CompiledVideoRequest(BaseModel):
    provider_type: str
    protocol_profile: str
    model_id: str
    operation: Literal["video.generate"]
    wire_request: dict[str, JsonValue]
    request_schema_version: str
    safe_request_summary: dict[str, JsonValue] = Field(default_factory=dict)
    reference_artifact_ids: list[UUID] = Field(default_factory=list)
    reference_fingerprints: list[str] = Field(default_factory=list)


class CompiledImageRequest(BaseModel):
    provider_type: str
    protocol_profile: str
    model_id: str
    operation: Literal["image.generate"]
    wire_request: dict[str, JsonValue]
    request_schema_version: str
    safe_request_summary: dict[str, JsonValue] = Field(default_factory=dict)
    reference_artifact_ids: list[UUID] = Field(default_factory=list)
    reference_fingerprints: list[str] = Field(default_factory=list)


class SubmissionResult(BaseModel):
    """One create attempt outcome. ``status`` mirrors the provider_operation
    status vocabulary so the caller can persist it directly. Synchronous image
    submissions carry the result URL in ``artifact_uri``; video submissions are
    asynchronous and are polled via the resume token."""

    remote_task_id: str | None = None
    remote_secondary_id: str | None = None
    query_kind: str | None = None
    status: str
    request_fingerprint: str | None = None
    request_summary: dict[str, JsonValue] = Field(default_factory=dict)
    resume_token: ProviderResumeToken | None = None
    artifact_uri: str | None = None
    error_code: str | None = None
    error: str | None = None
    retry_after_seconds: float | None = None
    http_status: int | None = None


class PollResult(BaseModel):
    status: str
    progress: float = 0.0
    artifact_uri: str | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None
    http_status: int | None = None


class CancelResult(BaseModel):
    status: str


class CostResult(BaseModel):
    amount: float | None = None
    currency: str = "USD"
    units: float = 1.0
    cost_status: Literal[
        "reported", "estimated_only", "not_reported", "reconciled"
    ] = "not_reported"

    @model_validator(mode="after")
    def infer_reported_amount(self) -> CostResult:
        if self.amount is not None and self.cost_status == "not_reported":
            self.cost_status = "reported"
        return self


@dataclass(frozen=True)
class ResolvedReference:
    """One resolved artifact reference handed to a Compiler: at most one of
    ``content_bytes`` / ``content_url`` is set. Byte download always happens at
    the platform boundary, never inside a Provider module."""

    role: str
    artifact_id: UUID
    content_bytes: bytes | None = None
    content_url: str | None = None
    mime_type: str = "image/png"
    fingerprint: str | None = None


class VideoCompiler(Protocol):
    def validate(self, intent: VideoGenerationIntentV1, model: ModelCapabilityManifest) -> None: ...
    async def compile(
        self,
        intent: VideoGenerationIntentV1,
        model: ModelCapabilityManifest,
        references: list[ResolvedReference],
        *,
        invoke_model_value: str,
    ) -> CompiledVideoRequest: ...


class ImageCompiler(Protocol):
    def validate(self, intent: ImageGenerationIntent, model: ModelCapabilityManifest) -> None: ...
    async def compile(
        self,
        intent: ImageGenerationIntent,
        model: ModelCapabilityManifest,
        references: list[ResolvedReference],
        *,
        invoke_model_value: str,
    ) -> CompiledImageRequest: ...


class ProviderRuntime(Protocol):
    async def submit_video(self, request: CompiledVideoRequest) -> SubmissionResult: ...
    async def submit_image(self, request: CompiledImageRequest) -> SubmissionResult: ...
    async def poll_video(self, resume: ProviderResumeToken) -> PollResult: ...
    async def cancel_video(self, resume: ProviderResumeToken) -> CancelResult: ...
    async def fetch_cost(self, resume: ProviderResumeToken) -> CostResult: ...


@dataclass(frozen=True)
class ConnectionContext:
    connection: ProviderConnection
    plugin: ProviderPlugin


@dataclass(frozen=True)
class ResolvedRuntime:
    runtime: ProviderRuntime
    image_compiler: ImageCompiler | None
    video_compiler: VideoCompiler | None
    connection: ProviderConnection
    binding: ProviderModelBinding | None = None
    catalog_entry: ModelCatalogEntry | None = None
    model_id: str | None = None
    invoke_model_value: str | None = None
    manifest_hash: str | None = None


class ProviderRuntimeResolver:
    """Builds a Runtime for a new submission from a SelectionPlan, or resumes an
    existing one from persisted ProviderOperation state. Resume never submits."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def resolve(
        self,
        *,
        plugin: ProviderPlugin,
        connection: ProviderConnection,
        binding: ProviderModelBinding,
        entry: ModelCatalogEntry,
        settings: Any = None,
    ) -> ResolvedRuntime:
        if plugin.runtime_factory is None or plugin.compiler_factory is None:
            raise RuntimeError(
                f"provider plugin {plugin.provider_type}/{plugin.protocol_profile} "
                "has no unified runtime/compiler"
            )
        runtime = plugin.runtime_factory(
            connection=connection,
            settings=settings,
            host=connection.base_url,
        )
        image_compiler, video_compiler = plugin.compiler_factory()
        if binding is not None and not binding.invoke_model_value:
            raise ValidationAppError(
                "provider model binding has no concrete invoke_model_value",
                details={"code": "MODEL_RUNTIME_IDENTITY_INVALID"},
            )
        if entry is not None and not entry.contract_manifest_hash:
            raise ValidationAppError(
                "model catalog entry has no manifest hash",
                details={"code": "MODEL_RUNTIME_IDENTITY_INVALID"},
            )
        return ResolvedRuntime(
            runtime=runtime,
            image_compiler=image_compiler,
            video_compiler=video_compiler,
            connection=connection,
            binding=binding,
            catalog_entry=entry,
            model_id=(
                f"{connection.provider_type}/{binding.model_id}"
                if binding is not None
                else None
            ),
            invoke_model_value=binding.invoke_model_value if binding is not None else None,
            manifest_hash=entry.contract_manifest_hash if entry is not None else None,
        )

    async def resolve_runtime_for_model_binding(
        self,
        *,
        model_binding_id: UUID,
        settings: Any = None,
    ) -> ResolvedRuntime:
        """Resolve the existing runtime from one concrete binding identity.

        This is the Professional entry point. It deliberately starts with the
        selected ``ProviderModelBinding`` and its catalog revision; it never
        searches seed manifests by provider/media and never chooses a sibling
        model when the selected identity is invalid.
        """
        binding = await self._session.get(ProviderModelBinding, model_binding_id)
        if binding is None:
            raise NotFoundError("provider model binding not found")
        connection = await self._session.get(ProviderConnection, binding.connection_id)
        if connection is None:
            raise NotFoundError("provider connection not found")
        entry = (
            await self._session.get(ModelCatalogEntry, binding.catalog_entry_id)
            if binding.catalog_entry_id is not None
            else None
        )
        if entry is None:
            raise ValidationAppError(
                "provider model binding has no catalog revision",
                details={"code": "MODEL_RUNTIME_IDENTITY_INVALID"},
            )
        reasons: list[str] = []
        if not binding.enabled:
            reasons.append("BINDING_DISABLED")
        if not connection.enabled:
            reasons.append("CONNECTION_DISABLED")
        if binding.workspace_id != connection.workspace_id:
            reasons.append("BINDING_CONNECTION_WORKSPACE_MISMATCH")
        if binding.catalog_entry_id != entry.id:
            reasons.append("BINDING_CATALOG_MISMATCH")
        if entry.model_id != binding.model_id:
            reasons.append("CATALOG_MODEL_MISMATCH")
        if entry.provider_type != connection.provider_type:
            reasons.append("CATALOG_PROVIDER_MISMATCH")
        if entry.protocol_profile != connection.protocol_profile:
            reasons.append("CATALOG_PROTOCOL_MISMATCH")
        if entry.media_kind != binding.media_type:
            reasons.append("CATALOG_MEDIA_MISMATCH")
        if entry.lifecycle != "active":
            reasons.append("CATALOG_LIFECYCLE_UNACCEPTABLE")
        if binding.capability_manifest_hash != entry.contract_manifest_hash:
            reasons.append("MANIFEST_HASH_MISMATCH")
        if not binding.invoke_model_value:
            reasons.append("INVOKE_MODEL_VALUE_MISSING")
        if reasons:
            raise ValidationAppError(
                "concrete provider model runtime identity is invalid",
                details={
                    "code": "MODEL_RUNTIME_IDENTITY_INVALID",
                    "reasons": reasons,
                    "model_binding_id": str(binding.id),
                    "catalog_entry_id": str(entry.id),
                },
            )
        from app.providers.registry import get_plugin

        plugin = get_plugin(connection.provider_type, connection.protocol_profile)
        return await self.resolve(
            plugin=plugin,
            connection=connection,
            binding=binding,
            entry=entry,
            settings=settings,
        )

    async def resume_runtime(
        self,
        *,
        plugin: ProviderPlugin,
        connection: ProviderConnection,
        settings: Any = None,
    ) -> ProviderRuntime:
        """Rebuild a runtime for polling/cancel/download from persisted state.
        Never submits."""
        if plugin.runtime_factory is None:
            raise RuntimeError(
                f"provider plugin {plugin.provider_type}/{plugin.protocol_profile} "
                "has no unified runtime"
            )
        runtime = plugin.runtime_factory(
            connection=connection,
            settings=settings,
            host=connection.base_url,
        )
        return cast(ProviderRuntime, runtime)
