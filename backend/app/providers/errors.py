"""Provider-layer normalized errors (V3 spec §40, §50).

Raw provider error strings/status codes never reach business code. A provider
error is normalized to a :class:`ProviderErrorCode` at the Adapter/Client
boundary; business code only ever sees these typed exceptions. All exceptions
derive from the shared :class:`AppError` so the API layer maps them to Problem
Details unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.shared.errors import AppError


class ProviderNotConfiguredError(AppError):
    """A configured model capability is required before a Provider call."""

    def __init__(self, message: str = "provider_not_configured") -> None:
        super().__init__(
            code="PROVIDER_NOT_CONFIGURED",
            message=message,
            status_code=422,
        )


class ProviderErrorCode(StrEnum):
    """Normalized provider error vocabulary (spec §40)."""

    INVALID_REQUEST = "invalid_request"
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNSUPPORTED_OPTION = "unsupported_option"
    UNSUPPORTED_INPUT_SLOT = "unsupported_input_slot"
    UNSUPPORTED_MODE = "unsupported_mode"
    INVALID_OPTION_COMBINATION = "invalid_option_combination"
    CONTENT_POLICY = "content_policy"
    TIMEOUT = "timeout"
    SUBMISSION_OUTCOME_UNKNOWN = "submission_outcome_unknown"
    CANCEL_NOT_SUPPORTED = "cancel_not_supported"
    RESUME_NOT_SUPPORTED = "resume_not_supported"
    UNKNOWN = "unknown"


class ProviderError(AppError):
    """Base provider-layer error. ``code`` is always a :class:`ProviderErrorCode`
    value so callers can branch on the normalized vocabulary, never raw text."""

    def __init__(
        self,
        code: ProviderErrorCode,
        message: str,
        *,
        status_code: int = 502,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=str(code.value),
            message=message,
            status_code=status_code,
            details=details,
        )


class UnsupportedCapabilityError(ProviderError):
    def __init__(
        self,
        capability: str,
        message: str = "model does not support this capability",
    ) -> None:
        super().__init__(
            ProviderErrorCode.UNSUPPORTED_CAPABILITY,
            message,
            status_code=422,
            details={"capability": capability},
        )


class UnsupportedOptionError(ProviderError):
    def __init__(self, option: str, message: str = "model does not support this option") -> None:
        super().__init__(
            ProviderErrorCode.UNSUPPORTED_OPTION,
            message,
            status_code=422,
            details={"option": option},
        )


class UnsupportedModeError(ProviderError):
    def __init__(self, mode_id: str | None) -> None:
        detail = {"code": "UNSUPPORTED_MODE"}
        if mode_id is not None:
            detail["mode_id"] = mode_id
        super().__init__(
            ProviderErrorCode.UNSUPPORTED_MODE,
            "mode_id is required or is not declared by the capability manifest",
            status_code=422,
            details=detail,
        )


class UnsupportedInputSlotError(ProviderError):
    def __init__(self, slot: str) -> None:
        super().__init__(
            ProviderErrorCode.UNSUPPORTED_INPUT_SLOT,
            f"input slot is not declared by the manifest: {slot}",
            status_code=422,
            details={"code": "UNSUPPORTED_INPUT_SLOT", "slot": slot},
        )


class InvalidOptionCombinationError(ProviderError):
    def __init__(
        self,
        message: str = "requested option combination is not supported",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            ProviderErrorCode.INVALID_OPTION_COMBINATION,
            message,
            status_code=422,
            details=details,
        )


class SubmissionOutcomeUnknownError(ProviderError):
    """The create request may have been accepted and billed, but its response
    was lost. Never auto-retry a paid create from this state (spec §51/§2.7)."""

    def __init__(self, message: str = "submission outcome is unknown") -> None:
        super().__init__(
            ProviderErrorCode.SUBMISSION_OUTCOME_UNKNOWN,
            message,
            status_code=503,
        )


class CancelNotSupportedError(ProviderError):
    def __init__(self, message: str = "provider does not support cancel") -> None:
        super().__init__(
            ProviderErrorCode.CANCEL_NOT_SUPPORTED,
            message,
            status_code=409,
        )


class ResumeNotSupportedError(ProviderError):
    def __init__(self, message: str = "provider does not support resume") -> None:
        super().__init__(
            ProviderErrorCode.RESUME_NOT_SUPPORTED,
            message,
            status_code=422,
        )


class ProviderStateMappingError(ProviderError):
    """A provider returned a status the adapter has no explicit mapping for.

    Unknown behavior must be explicit (spec invariant 5): never default an
    unmapped provider status to SUBMITTED, or a contract drift could hide a
    terminal state behind a poll loop. The adapter owner must add the mapping
    (or normalize at the runtime boundary) instead.
    """

    def __init__(self, provider_status: str) -> None:
        super().__init__(
            ProviderErrorCode.UNKNOWN,
            f"unknown provider status: {provider_status}",
            status_code=502,
            details={"provider_status": provider_status},
        )


class ResumeTokenUnavailableError(ProviderError):
    """The adapter has no way to obtain the durable resume token for a remote
    task. Durable poll/cancel/cost must be driven by the persisted
    ``ProviderOperation.resume_token`` (Option A) or a wired token provider —
    never by process-local memory."""

    def __init__(self, remote_task_id: str) -> None:
        super().__init__(
            ProviderErrorCode.RESUME_NOT_SUPPORTED,
            "durable resume requires a wired token provider or the persisted "
            "ProviderOperation resume_token",
            status_code=503,
            details={"remote_task_id": remote_task_id},
        )


class TransportFailureKind(StrEnum):
    """Classification of a failed transport attempt (spec §50.3). Decides whether
    a create may be retried and under what submission semantics."""

    DEFINITELY_NOT_SENT = "definitely_not_sent"
    RESPONSE_RECEIVED = "response_received"
    SUBMISSION_AMBIGUOUS = "submission_ambiguous"


@dataclass
class TransportFailure:
    """Normalized transport failure classification. ``SUBMISSION_AMBIGUOUS``
    must escalate to :class:`SubmissionOutcomeUnknownError` — the request may
    have been accepted and billed."""

    kind: TransportFailureKind
    detail: str

    @property
    def ambiguous(self) -> bool:
        return self.kind is TransportFailureKind.SUBMISSION_AMBIGUOUS

    def to_error(self) -> ProviderError:
        if self.kind is TransportFailureKind.SUBMISSION_AMBIGUOUS:
            return SubmissionOutcomeUnknownError(self.detail)
        return ProviderError(
            ProviderErrorCode.PROVIDER_UNAVAILABLE,
            self.detail,
            status_code=503,
        )
