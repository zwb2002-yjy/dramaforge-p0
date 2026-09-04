"""Model-profile error codes (spec §96). Stable codes surfaced in API details."""

from __future__ import annotations

from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

MODEL_PROFILE_NOT_FOUND = "MODEL_PROFILE_NOT_FOUND"
MODEL_PROFILE_MODEL_NOT_FOUND = "MODEL_PROFILE_MODEL_NOT_FOUND"
MODEL_PROFILE_CAPABILITY_MISMATCH = "MODEL_PROFILE_CAPABILITY_MISMATCH"
MODEL_PROFILE_VERSION_CONFLICT = "MODEL_PROFILE_VERSION_CONFLICT"
MODEL_PROFILE_NATIVE_OPTION_INVALID = "MODEL_PROFILE_NATIVE_OPTION_INVALID"
MODEL_PROFILE_SLOT_UNKNOWN = "MODEL_PROFILE_SLOT_UNKNOWN"
MODEL_PROFILE_MODEL_DISABLED = "MODEL_PROFILE_MODEL_DISABLED"
MODEL_PROFILE_MODEL_NOT_CONFIGURED = "MODEL_PROFILE_MODEL_NOT_CONFIGURED"
MODEL_PROFILE_NO_AVAILABLE_MODEL = "MODEL_PROFILE_NO_AVAILABLE_MODEL"


def profile_not_found() -> NotFoundError:
    return NotFoundError(
        "model profile not found",
        details={"code": MODEL_PROFILE_NOT_FOUND},
    )


def profile_model_not_found(model_id: str) -> ValidationAppError:
    return ValidationAppError(
        f"model profile references unknown model: {model_id}",
        details={"code": MODEL_PROFILE_MODEL_NOT_FOUND, "model_id": model_id},
    )


def profile_capability_mismatch(
    slot: str, model_id: str, capability: str | None = None,
) -> ValidationAppError:
    details: dict[str, object] = {
        "code": MODEL_PROFILE_CAPABILITY_MISMATCH,
        "slot": slot,
        "model_id": model_id,
    }
    if capability is not None:
        details["capability"] = capability
    return ValidationAppError(
        f"model {model_id} does not support the slot {slot} requirements",
        details=details,
    )


def profile_version_conflict(expected: int, actual: int) -> ConflictError:
    return ConflictError(
        "model profile version conflict",
        details={
            "code": MODEL_PROFILE_VERSION_CONFLICT,
            "expected_version": expected,
            "actual_version": actual,
        },
    )


def profile_native_option_invalid(option: str, model_id: str, reason: str) -> ValidationAppError:
    return ValidationAppError(
        f"native option {option} is invalid for {model_id}: {reason}",
        details={
            "code": MODEL_PROFILE_NATIVE_OPTION_INVALID,
            "option": option,
            "model_id": model_id,
        },
    )


def profile_slot_unknown(slot: str) -> ValidationAppError:
    return ValidationAppError(
        f"unknown model slot: {slot}",
        details={"code": MODEL_PROFILE_SLOT_UNKNOWN, "slot": slot},
    )


def profile_model_disabled(model_id: str) -> ValidationAppError:
    return ValidationAppError(
        f"model is disabled: {model_id}",
        details={"code": MODEL_PROFILE_MODEL_DISABLED, "model_id": model_id},
    )


def profile_model_not_configured(model_id: str) -> ValidationAppError:
    return ValidationAppError(
        f"model is not configured: {model_id}",
        details={"code": MODEL_PROFILE_MODEL_NOT_CONFIGURED, "model_id": model_id},
    )


def profile_no_available_model(capability: str) -> ValidationAppError:
    return ValidationAppError(
        f"no available model for capability: {capability}",
        details={
            "code": MODEL_PROFILE_NO_AVAILABLE_MODEL,
            "capability": capability,
        },
    )
