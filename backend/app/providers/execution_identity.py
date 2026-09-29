"""Secret-free execution identity contracts for Professional Provider runs.

The identity is an evidence snapshot, not another persistence model.  It is
frozen before the first Provider submission and contains only stable IDs,
versioned execution facts, and sanitized request evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

_SECRET_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "ciphertext",
    "header",
    "bearer",
    "download_url",
    "grant",
    "remote_task_id",
    "remotetaskid",
    "provider_operation_id",
    "provideroperationid",
    "resume_token",
    "resumetoken",
)


def _validate_safe_evidence(value: JsonValue, *, path: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise ValueError(
                    f"execution identity contains forbidden evidence key: {path}.{key}"
                )
            _validate_safe_evidence(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_safe_evidence(child, path=f"{path}[{index}]")


class ExecutionIdentityReference(BaseModel):
    """Sanitized reference identity; never stores bytes or a delivery URL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str = Field(min_length=1, max_length=80)
    artifact_id: UUID
    mime_type: str = Field(min_length=1, max_length=120)
    fingerprint: str | None = Field(default=None, max_length=128)


class ExecutionIdentitySnapshot(BaseModel):
    """Immutable, JSON-safe identity of one concrete Provider execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_model: str | None = Field(default=None, max_length=240)
    resolved_model: str = Field(min_length=1, max_length=240)
    resolution_source: str = Field(min_length=1, max_length=80)

    provider_model_binding_id: UUID
    catalog_entry_id: UUID
    model_revision: str = Field(min_length=1, max_length=120)
    manifest_hash: str = Field(min_length=1, max_length=128)
    invoke_model_value: str = Field(min_length=1, max_length=240)

    connection_id: UUID
    connection_revision_id: UUID
    # Design §9 names this same field ``provider_connection_revision_id``;
    # retain both spellings in the JSON contract while enforcing one identity.
    provider_connection_revision_id: UUID | None = None
    credential_revision_id: UUID

    capability: str = Field(min_length=1, max_length=120)
    mode_id: str = Field(min_length=1, max_length=120)
    effective_options: dict[str, JsonValue] = Field(default_factory=dict)
    resolved_references: list[ExecutionIdentityReference] = Field(default_factory=list)
    translation_report: dict[str, JsonValue] = Field(default_factory=dict)
    request_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy through validation so frozen evidence cannot bypass the gate.

        Pydantic's default ``model_copy(update=...)`` intentionally skips
        validation.  That behavior is unsafe for this security-sensitive
        snapshot because it could inject a secret-bearing evidence key after
        construction.
        """
        if update is None:
            return super().model_copy(deep=deep)
        data = self.model_dump(mode="python")
        data.update(update)
        return type(self).model_validate(data)

    @model_validator(mode="after")
    def validate_identity(self) -> ExecutionIdentitySnapshot:
        if self.provider_connection_revision_id is None:
            object.__setattr__(
                self,
                "provider_connection_revision_id",
                self.connection_revision_id,
            )
        elif self.provider_connection_revision_id != self.connection_revision_id:
            raise ValueError("connection revision identity has conflicting field values")
        _validate_safe_evidence(self.effective_options, path="effective_options")
        _validate_safe_evidence(self.translation_report, path="translation_report")
        return self


class GlobalModelTargetIdentity(BaseModel):
    """One immutable Global capability revision, independent of its invoke ID."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["global_model"] = "global_model"
    model_capability_revision_id: UUID
    canonical_model_id: str = Field(min_length=1, max_length=160)
    model_revision: str = Field(min_length=1, max_length=120)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConnectionModelTargetIdentity(BaseModel):
    """A connection-scoped capability; it has no Global catalog identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["connection_model"] = "connection_model"
    connection_discovered_model_id: UUID
    connection_model_capability_revision_id: UUID
    connection_capability_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_model_id: str = Field(min_length=1, max_length=240)


class PolicyRevisionIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    product_policy_revision_id: UUID
    product_policy_id: UUID
    policy_revision: int = Field(gt=0)
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProtocolRevisionIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_contract_revision_id: UUID
    protocol_contract_id: UUID
    protocol_revision: int = Field(gt=0)
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class HandlerRevisionIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_handler_revision_id: UUID
    runtime_handler_id: UUID
    handler_revision: int = Field(gt=0)
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CutoverExecutionIdentitySnapshot(BaseModel):
    """V7 frozen Create/recovery identity; not yet used by the current Worker.

    The distinct target variants prevent a Dynamic model from acquiring a
    fictitious Global catalog identity. Runtime cutover must wire this exact
    snapshot to Dispatch, Create and recovery together.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID
    target: GlobalModelTargetIdentity | ConnectionModelTargetIdentity = Field(discriminator="kind")
    invoke_model_value: str = Field(min_length=1, max_length=240)
    policy: PolicyRevisionIdentity
    protocol: ProtocolRevisionIdentity
    handler: HandlerRevisionIdentity
    connection_id: UUID
    connection_revision_id: UUID
    credential_revision_id: UUID
    operation: str = Field(min_length=1, max_length=120)
    matched_input_contract: str = Field(min_length=1, max_length=120)
    resolved_references: list[ExecutionIdentityReference] = Field(default_factory=list)
    requested_options: dict[str, JsonValue] = Field(default_factory=dict)
    effective_options: dict[str, JsonValue] = Field(default_factory=dict)
    transformations: list[dict[str, JsonValue]] = Field(default_factory=list)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_cutover_identity(self) -> CutoverExecutionIdentitySnapshot:
        if (
            isinstance(self.target, ConnectionModelTargetIdentity)
            and self.target.remote_model_id != self.invoke_model_value
        ):
            raise ValueError("Dynamic target and invoke model identities differ")
        _validate_safe_evidence(self.requested_options, path="requested_options")
        _validate_safe_evidence(self.effective_options, path="effective_options")
        for index, transformation in enumerate(self.transformations):
            _validate_safe_evidence(transformation, path=f"transformations[{index}]")
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is None:
            return super().model_copy(deep=deep)
        data = self.model_dump(mode="python")
        data.update(update)
        return type(self).model_validate(data)


@dataclass(frozen=True)
class FrozenProviderConnection:
    """Runtime connection view reconstructed from ProviderConnectionRevision."""

    id: UUID
    workspace_id: UUID
    provider_type: str
    protocol_profile: str
    base_url: str
    credential_id: UUID
    credential_revision: int
    enabled: bool = True
