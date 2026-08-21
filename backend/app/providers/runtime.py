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
        return ResolvedRuntime(
            runtime=runtime,
            image_compiler=image_compiler,
            video_compiler=video_compiler,
            connection=connection,
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
