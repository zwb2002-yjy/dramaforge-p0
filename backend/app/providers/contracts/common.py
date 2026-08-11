"""Shared capability-contract primitives (pure Pydantic, no ORM deps)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class GenerationStatus(StrEnum):
    """V3 generation status machine (spec §41). The repo's persisted
    ``provider_operations.status`` vocabulary is mapped onto this at the
    operation boundary (see Phase 5); the V3 enum stays the business-level
    status language."""

    CREATED = "created"
    VALIDATING = "validating"
    SUBMITTING = "submitting"
    SUBMIT_UNKNOWN = "submit_unknown"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ArtifactRef(BaseModel):
    """Stable artifact identity. Never a signed URL or provider temp URL — those
    are transient delivery grants (spec §13, invariant: signed URLs are not
    artifact identity)."""

    artifact_id: str
    revision: str | None = None


class ResolvedArtifact(BaseModel):
    """Internal resolution of an :class:`ArtifactRef` into concrete delivery
    material. Not exposed to the public generation API (spec §13). At most one
    of ``content_bytes`` / ``signed_url`` is set for a given transport."""

    artifact_id: str
    mime_type: str
    sha256: str | None = None
    size_bytes: int | None = None
    local_path: str | None = None
    signed_url: str | None = None
    provider_file_id: str | None = None
    content_bytes: bytes | None = None


class ExecutionContext(BaseModel):
    """Audit + routing context for one generation attempt. Carries identity
    references only — never secrets (spec §24/§64)."""

    trace_id: str
    operation_id: str | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    credential_id: str | None = None
    idempotency_key: str | None = None


class ProviderCreateResult(BaseModel):
    """Normalized outcome of one create submission (spec §39)."""

    status: GenerationStatus
    remote_task_id: str | None = None
    artifact_uri: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderPollResult(BaseModel):
    """Normalized poll outcome (spec §39)."""

    status: GenerationStatus
    progress: float | None = None
    artifact_uri: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderCancelResult(BaseModel):
    """Normalized cancel outcome (spec §39)."""

    status: GenerationStatus
    accepted: bool


class ProviderCostResult(BaseModel):
    """Normalized cost outcome (spec §39)."""

    currency: str | None = None
    amount: Decimal | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
