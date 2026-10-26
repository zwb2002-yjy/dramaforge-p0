"""Unified Provider runtime/compiler contracts and resolver (stage B).

Single wire owner: a Compiler produces ``CompiledVideoRequest.wire_request`` and
the Runtime ``submit_*`` sends it verbatim. Existing HubClient methods become
compatible wrappers over the same low-level transport. Resume is driven by a
sanitized :class:`ProviderResumeToken` persisted on ``ProviderOperation`` —
never by current Feature Flags or the current Project binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator
from sqlalchemy import select

from app.providers.catalog_models import ModelCatalogEntry
from app.providers.execution_identity import (
    ExecutionIdentitySnapshot,
    FrozenProviderConnection,
)
from app.providers.intents import (
    ImageGenerationIntent,
    VideoGenerationIntentV1,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)
from app.security.models import EncryptedProviderCredential
from app.shared.errors import NotFoundError, ValidationAppError

if TYPE_CHECKING:
    from app.providers.model_resolution import ExecutionModelResolution
    from app.providers.registry import ProviderPlugin

PROVIDER_CONTENT_URI = "provider-content"


class ProviderResumeToken(BaseModel):
    """Sanitized resume context. Never carries secrets, raw media, short-lived
    URLs, or a full unredacted wire body."""

    provider_type: str
    protocol_profile: str
    remote_task_id: str
    remote_secondary_id: str | None = None
    query_kind: str | None = None
    opaque_state: dict[str, JsonValue] = Field(default_factory=dict)


def require_resume_token_identity(
    token: ProviderResumeToken,
    *,
    remote_task_id: str | None,
    provider_type: str,
    protocol_profile: str | None,
    remote_secondary_id: str | None,
) -> None:
    """Validate persisted remote identity before constructing or calling a Runtime."""
    if (
        not remote_task_id
        or token.remote_task_id != remote_task_id
        or token.provider_type != provider_type
        or token.protocol_profile != protocol_profile
        or token.remote_secondary_id != remote_secondary_id
    ):
        raise ValidationAppError(
            "恢复令牌与已提交任务身份不一致，必须人工核对",
            details={"code": "RESUME_TOKEN_IDENTITY_MISMATCH"},
        )


def require_operation_identity(identity: ExecutionIdentitySnapshot, operation: Any) -> None:
    """Audit and recovery share the exact persisted input/model identity check."""
    for actual, expected in (
        (operation.connection_id, identity.connection_id),
        (operation.provider_connection_revision_id, identity.connection_revision_id),
        (operation.credential_revision_id, identity.credential_revision_id),
        (operation.model_binding_id, identity.provider_model_binding_id),
        (operation.catalog_entry_id, identity.catalog_entry_id),
        (operation.capability_manifest_hash, identity.manifest_hash),
        (operation.actual_model, identity.invoke_model_value),
        (operation.request_fingerprint, identity.request_fingerprint),
    ):
        if actual != expected:
            raise ValidationAppError(
                "已提交任务与冻结执行身份不一致，必须人工核对",
                details={"code": "EXECUTION_IDENTITY_MISMATCH"},
            )


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


def validate_compiled_submission(
    request: CompiledImageRequest | CompiledVideoRequest,
    *,
    provider_type: str,
    protocol_profile: str,
    operation: Literal["image.generate", "video.generate"],
) -> None:
    """Check the existing JSON media seam before credentials reach the network.

    This is not payload compilation or model selection. The compiler's chosen
    wire model must match its envelope, and the envelope must target this runtime.
    Never repair a mismatch by substituting a configured default or rebuilding
    the body. Errors intentionally omit payloads and credential values.
    """
    if (request.provider_type, request.protocol_profile, request.operation) != (
        provider_type,
        protocol_profile,
        operation,
    ):
        raise ValueError("compiled request does not match runtime provider/profile/operation")
    if not request.model_id.strip() or request.wire_request.get("model") != request.model_id:
        raise ValueError("compiled wire model does not match request model_id")


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
    cost_status: Literal["reported", "estimated_only", "not_reported", "reconciled"] = (
        "not_reported"
    )

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
    byte_size: int | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None


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
        from app.config import Settings as _Settings
        from app.providers.egress import guarded_provider_transport

        # Connection-time SSRF closure (joint-review P1): every runtime
        # socket resolves and validates its destination before credentials
        # leave the process; the factory's transport parameter keeps test
        # doubles working when they are injected directly.
        egress_settings = settings if isinstance(settings, _Settings) else None
        runtime = plugin.runtime_factory(
            connection=connection,
            settings=settings,
            host=connection.base_url,
            transport=guarded_provider_transport(settings=egress_settings),
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
                f"{connection.provider_type}/{binding.model_id}" if binding is not None else None
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
        if entry.catalog_source != "protocol_contract" and entry.model_id != binding.model_id:
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
        elif (
            entry.catalog_source == "protocol_contract"
            and binding.invoke_model_value != binding.model_id
        ):
            reasons.append("INVOKE_MODEL_IDENTITY_MISMATCH")
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

    async def resolve_runtime_for_resolution(
        self,
        *,
        resolution: ExecutionModelResolution,
        workspace_id: UUID,
        connection_revision_id: UUID | None = None,
        credential_revision_id: UUID | None = None,
        settings: Any = None,
    ) -> ResolvedRuntime:
        """Build a runtime from a frozen model resolution and connection revision.

        This is the pre-submission counterpart to
        :meth:`resolve_runtime_for_identity`.  Workbench NodeRuns persist a
        typed ``ExecutionModelResolution`` before a ProviderOperation exists;
        they still must not build a runtime from the mutable current
        ``ProviderConnection``.  A provisional, secret-free identity lets the
        same revision-aware validation path construct the compiler/runtime.
        The final request fingerprint and reference evidence are frozen by the
        caller immediately before submission.
        """
        if (
            resolution.status != "RESOLVED"
            or resolution.provider_model_binding_id is None
            or resolution.provider_connection_id is None
            or resolution.catalog_entry_id is None
            or resolution.resolved_model_id is None
            or resolution.model_revision is None
            or resolution.manifest_hash is None
            or resolution.invoke_model_value is None
        ):
            raise ValidationAppError(
                "frozen execution model resolution is incomplete",
                details={"code": "EXECUTION_IDENTITY_MODEL_UNAVAILABLE"},
            )
        revision_id = connection_revision_id or resolution.provider_connection_revision_id
        credential_id = credential_revision_id or resolution.credential_revision_id
        if revision_id is None or credential_id is None:
            raise ValidationAppError(
                "frozen execution model has no connection revision",
                details={"code": "EXECUTION_IDENTITY_REVISION_UNAVAILABLE"},
            )
        identity = ExecutionIdentitySnapshot(
            requested_model=resolution.requested_model_id,
            resolved_model=resolution.resolved_model_id,
            resolution_source=resolution.source,
            provider_model_binding_id=resolution.provider_model_binding_id,
            catalog_entry_id=resolution.catalog_entry_id,
            model_revision=resolution.model_revision,
            manifest_hash=resolution.manifest_hash,
            invoke_model_value=resolution.invoke_model_value,
            connection_id=resolution.provider_connection_id,
            connection_revision_id=revision_id,
            credential_revision_id=credential_id,
            capability=resolution.capability.value,
            mode_id=resolution.mode_id or "resolved",
            effective_options=cast(dict[str, JsonValue], resolution.native_options),
            request_fingerprint="0" * 64,
        )
        return await self.resolve_runtime_for_identity(
            identity=identity,
            workspace_id=workspace_id,
            settings=settings,
        )

    async def resolve_runtime_for_identity(
        self,
        *,
        identity: ExecutionIdentitySnapshot,
        workspace_id: UUID,
        operation: Any | None = None,
        settings: Any = None,
    ) -> ResolvedRuntime:
        """Resolve runtime/compiler from a frozen execution identity.

        The mutable ``ProviderConnection`` is joined only to authorize the
        revision's workspace/connection ownership. Its current host, protocol,
        and credential pointer are never used to build the runtime.
        """
        if operation is not None:
            require_operation_identity(identity, operation)

        revision = await self._session.scalar(
            select(ProviderConnectionRevision)
            .join(
                ProviderConnection,
                ProviderConnection.id == ProviderConnectionRevision.connection_id,
            )
            .where(
                ProviderConnectionRevision.id == identity.connection_revision_id,
                ProviderConnectionRevision.connection_id == identity.connection_id,
                ProviderConnection.workspace_id == workspace_id,
            )
        )
        if revision is None:
            raise ValidationAppError(
                "frozen provider connection revision is unavailable",
                details={"code": "EXECUTION_IDENTITY_REVISION_UNAVAILABLE"},
            )
        if revision.credential_revision_id != identity.credential_revision_id:
            raise ValidationAppError(
                "frozen connection and credential revisions do not match",
                details={"code": "EXECUTION_IDENTITY_MISMATCH"},
            )

        binding = await self._session.scalar(
            select(ProviderModelBinding).where(
                ProviderModelBinding.id == identity.provider_model_binding_id,
                ProviderModelBinding.workspace_id == workspace_id,
                ProviderModelBinding.connection_id == identity.connection_id,
            )
        )
        entry = (
            await self._session.get(ModelCatalogEntry, identity.catalog_entry_id)
            if binding is not None
            else None
        )
        if (
            binding is None
            or entry is None
            or binding.catalog_entry_id != identity.catalog_entry_id
            or identity.resolved_model != f"{entry.provider_type}/{binding.model_id}"
            or binding.invoke_model_value != identity.invoke_model_value
            or entry.provider_type != revision.provider_type
            or entry.protocol_profile != revision.protocol_profile
            or (entry.catalog_source != "protocol_contract" and entry.model_id != binding.model_id)
            or (
                entry.catalog_source == "protocol_contract"
                and binding.invoke_model_value != binding.model_id
            )
            or entry.model_revision != identity.model_revision
            or entry.contract_manifest_hash != identity.manifest_hash
        ):
            raise ValidationAppError(
                "frozen model identity is unavailable or has changed",
                details={"code": "EXECUTION_IDENTITY_MODEL_UNAVAILABLE"},
            )
        credential = await self._session.scalar(
            select(EncryptedProviderCredential).where(
                EncryptedProviderCredential.id == identity.credential_revision_id,
                EncryptedProviderCredential.workspace_id == workspace_id,
            )
        )
        if credential is None:
            raise ValidationAppError(
                "frozen credential revision is unavailable",
                details={"code": "EXECUTION_IDENTITY_CREDENTIAL_UNAVAILABLE"},
            )
        from app.providers.registry import get_plugin
        from app.providers.workspace_credentials import runtime_connection_settings

        try:
            plugin = get_plugin(revision.provider_type, revision.protocol_profile)
        except LookupError as exc:
            raise ValidationAppError(
                "frozen provider plugin is unavailable",
                details={"code": "PROVIDER_PLUGIN_UNKNOWN"},
            ) from exc
        if credential.provider != plugin.credential_key:
            raise ValidationAppError(
                "frozen credential provider does not match connection protocol",
                details={"code": "EXECUTION_IDENTITY_CREDENTIAL_MISMATCH"},
            )
        if operation is not None:
            if operation.actual_provider != revision.provider_type:
                raise ValidationAppError(
                    "operation and frozen provider mismatch",
                    details={"code": "EXECUTION_IDENTITY_MISMATCH"},
                )
            if operation.protocol_profile != revision.protocol_profile:
                raise ValidationAppError(
                    "operation and frozen protocol mismatch",
                    details={"code": "EXECUTION_IDENTITY_MISMATCH"},
                )

        frozen_connection = FrozenProviderConnection(
            id=identity.connection_id,
            workspace_id=workspace_id,
            provider_type=revision.provider_type,
            protocol_profile=revision.protocol_profile,
            base_url=revision.base_url,
            credential_id=revision.credential_revision_id,
            credential_revision=credential.revision_no,
            enabled=True,
        )
        frozen_settings = await runtime_connection_settings(
            self._session,
            connection=frozen_connection,  # type: ignore[arg-type]
            settings=settings,
        )
        return await self.resolve(
            plugin=plugin,
            connection=frozen_connection,  # type: ignore[arg-type]
            binding=binding,
            entry=entry,
            settings=frozen_settings,
        )

    async def resume_runtime_for_identity(
        self,
        *,
        identity: ExecutionIdentitySnapshot,
        workspace_id: UUID,
        operation: Any | None = None,
        settings: Any = None,
    ) -> ProviderRuntime:
        """Rebuild only the runtime for an existing frozen operation."""
        from app.providers.execution_contract import execution_contract_gaps

        gaps = execution_contract_gaps(identity.execution_contract)
        if gaps:
            raise ValidationAppError(
                "历史任务的执行合同无法精确核验，请人工核对后恢复",
                details={"code": gaps[0], "gaps": list(gaps)},
            )
        if (
            operation is not None
            and identity.execution_contract is not None
            and (
                identity.execution_contract.provider_type != operation.actual_provider
                or identity.execution_contract.protocol_profile != operation.protocol_profile
            )
        ):
            raise ValidationAppError(
                "frozen execution contract does not match operation protocol",
                details={"code": "EXECUTION_IDENTITY_MISMATCH"},
            )
        resolved = await self.resolve_runtime_for_identity(
            identity=identity,
            workspace_id=workspace_id,
            operation=operation,
            settings=settings,
        )
        return resolved.runtime
