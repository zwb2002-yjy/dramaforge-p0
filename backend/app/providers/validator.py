"""Strict capability validator (spec Appendix B, §2.6, §29.1).

Before any Provider call, a request is validated against the model's
:class:`CapabilitySpec` in a fixed order: input slots → common options → native
options → cross-field constraints. Unsupported behavior is an explicit error
(strict mode), never a silent drop. The validator is pure: no I/O, no DB.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.providers.contracts.image import ImageGenerateRequest
from app.providers.contracts.video import (
    FirstLastFrameVideoRequest,
    ImageToVideoRequest,
    ReferenceToVideoRequest,
)
from app.providers.errors import (
    InvalidOptionCombinationError,
    UnsupportedInputSlotError,
    UnsupportedOptionError,
)
from app.providers.manifest import CapabilitySpec, InputSlotSpec, ParameterSpec
from app.providers.reference_roles import canonical_reference_role
from app.providers.runtime import ResolvedReference

# Top-level request fields that count as "common options" for strict checking.
# Artifact refs and prompt/inputs are validated separately (slots/contract).
_COMMON_OPTION_FIELDS: frozenset[str] = frozenset(
    {
        "duration_seconds",
        "resolution",
        "aspect_ratio",
        "seed",
        "size",
        "max_tokens",
        "system",
        "voice",
        "language",
    }
)


def _role_counts(request: Any) -> dict[str, int]:
    """Per-input-slot artifact counts, always keyed by canonical role."""
    counts: dict[str, int] = {}
    if isinstance(request, ImageToVideoRequest):
        counts["first_frame"] = 1
    elif isinstance(request, FirstLastFrameVideoRequest):
        counts["first_frame"] = 1
        counts["last_frame"] = 1
    elif isinstance(request, ReferenceToVideoRequest):
        if request.reference_images:
            counts["reference_image"] = len(request.reference_images)
        if request.reference_audio:
            counts["reference_audio"] = len(request.reference_audio)
        if request.reference_videos:
            counts["reference_video"] = len(request.reference_videos)
    elif isinstance(request, ImageGenerateRequest) and request.reference_images:
        counts["reference_image"] = len(request.reference_images)
    return counts


def _resolved_reference_roles(resolved_references: list[ResolvedReference]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reference in resolved_references:
        role = canonical_reference_role(reference.role)
        if role is None:
            raise UnsupportedInputSlotError(reference.role)
        counts[role] = counts.get(role, 0) + 1
    return counts


def _mime_matches(mime_type: str, patterns: list[str]) -> bool:
    mime = mime_type.lower().strip()
    return any(
        pattern == "*/*"
        or pattern.lower() == mime
        or (pattern.endswith("/*") and mime.startswith(pattern[:-1].lower()))
        for pattern in patterns
    )


def _requested_options(request: Any) -> dict[str, Any]:
    if not isinstance(request, BaseModel):
        return {}
    return {
        key: value
        for key, value in request.model_dump(exclude_unset=False).items()
        if key in _COMMON_OPTION_FIELDS and value is not None
    }


def _validate_input_slots(
    request: Any,
    spec: CapabilitySpec,
    *,
    resolved_references: list[ResolvedReference] | None = None,
) -> None:
    counts = _role_counts(request)
    if resolved_references is not None:
        resolved_counts = _resolved_reference_roles(resolved_references)
        if resolved_counts != counts:
            raise InvalidOptionCombinationError(
                "resolved references do not match request references",
                details={
                    "code": "RESOLVED_REFERENCE_MISMATCH",
                    "request_counts": counts,
                    "resolved_counts": resolved_counts,
                },
            )
        counts = resolved_counts
    for role, count in counts.items():
        canonical_role = canonical_reference_role(role)
        if canonical_role is None or canonical_role not in spec.input_slots:
            raise UnsupportedInputSlotError(role)
        _check_slot(spec.input_slots[canonical_role], canonical_role, count)
    # Required slots must be present.
    for role, slot in spec.input_slots.items():
        if slot.required and counts.get(role, 0) < 1:
            raise InvalidOptionCombinationError(
                f"required input slot is missing: {role}",
                details={"slot": role},
            )

    if resolved_references is not None:
        for reference in resolved_references:
            reference_role = canonical_reference_role(reference.role)
            if reference_role is None or reference_role not in spec.input_slots:
                continue
            slot = spec.input_slots[reference_role]
            if slot.media_types and not _mime_matches(reference.mime_type, slot.media_types):
                raise InvalidOptionCombinationError(
                    f"input slot {reference_role} does not accept MIME type {reference.mime_type}",
                    details={
                        "code": "INPUT_MEDIA_TYPE_MISMATCH",
                        "slot": reference_role,
                        "mime_type": reference.mime_type,
                        "media_types": slot.media_types,
                    },
                )


def _check_slot(slot: InputSlotSpec, role: str, count: int) -> None:
    if count < slot.minimum:
        raise InvalidOptionCombinationError(
            f"input slot {role} needs at least {slot.minimum} artifacts",
            details={"slot": role, "minimum": slot.minimum, "actual": count},
        )
    if slot.maximum is not None and count > slot.maximum:
        raise InvalidOptionCombinationError(
            f"input slot {role} accepts at most {slot.maximum} artifacts",
            details={"slot": role, "maximum": slot.maximum, "actual": count},
        )


def _validate_options(request: Any, spec: CapabilitySpec) -> None:
    for option, value in _requested_options(request).items():
        declared = spec.common_options.get(option)
        if declared is None:
            raise UnsupportedOptionError(option)
        validate_parameter(option, value, declared)
    for option, value in dict(getattr(request, "native_options", {}) or {}).items():
        declared = spec.native_options.get(option)
        if declared is None:
            raise UnsupportedOptionError(option)
        validate_parameter(option, value, declared)


def validate_parameter(name: str, value: Any, spec: ParameterSpec) -> None:
    """Validate one option value against its :class:`ParameterSpec`.

    The manifest schema is a runtime contract, not just UI metadata (spec §16):
    type, enum, numeric bounds and array bounds are all enforced here so an
    unsupported native value never reaches the Provider as a 400. This is the
    single validator used by both common and native options.
    """
    if value is None:
        if spec.required:
            raise InvalidOptionCombinationError(
                f"option {name} is required",
                details={"option": name},
            )
        return
    if spec.type == "string" and not isinstance(value, str):
        raise UnsupportedOptionError(name, message=f"{name} must be a string")
    if spec.type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise UnsupportedOptionError(name, message=f"{name} must be an integer")
    if spec.type == "number" and (not isinstance(value, int | float) or isinstance(value, bool)):
        raise UnsupportedOptionError(name, message=f"{name} must be a number")
    if spec.type == "boolean" and not isinstance(value, bool):
        raise UnsupportedOptionError(name, message=f"{name} must be a boolean")
    if spec.type == "array" and not isinstance(value, list):
        raise UnsupportedOptionError(name, message=f"{name} must be an array")
    if spec.type == "object" and not isinstance(value, dict):
        raise UnsupportedOptionError(name, message=f"{name} must be an object")
    if spec.enum is not None and value not in spec.enum:
        raise UnsupportedOptionError(
            name,
            message=f"{name}={value!r} is not one of {spec.enum}",
        )
    if isinstance(value, int | float) and not isinstance(value, bool):
        if spec.minimum is not None and value < spec.minimum:
            raise UnsupportedOptionError(
                name,
                message=f"{name}={value} is below minimum {spec.minimum}",
            )
        if spec.maximum is not None and value > spec.maximum:
            raise UnsupportedOptionError(
                name,
                message=f"{name}={value} is above maximum {spec.maximum}",
            )
    if isinstance(value, list):
        if spec.min_items is not None and len(value) < spec.min_items:
            raise UnsupportedOptionError(
                name,
                message=f"{name} has fewer than {spec.min_items} items",
            )
        if spec.max_items is not None and len(value) > spec.max_items:
            raise UnsupportedOptionError(
                name,
                message=f"{name} has more than {spec.max_items} items",
            )


def _validate_constraints(request: Any, spec: CapabilitySpec) -> None:
    requested = _requested_options(request)
    constraints = spec.constraints
    # mutually_exclusive: at most one member of each group may be set.
    for group in constraints.mutually_exclusive:
        present = [name for name in group if requested.get(name) is not None]
        if len(present) > 1:
            raise InvalidOptionCombinationError(
                "options are mutually exclusive: " + ", ".join(present),
                details={"mutually_exclusive": present},
            )
    # requires: key present -> required options must be present.
    for key, required in constraints.requires.items():
        if requested.get(key) is not None:
            missing = [name for name in required if requested.get(name) is None]
            if missing:
                raise InvalidOptionCombinationError(
                    f"{key} requires " + ", ".join(missing),
                    details={"requires": missing, "of": key},
                )
    # conditional: when matches -> require/forbid/allowed checks.
    for condition in constraints.conditional:
        if not _when_matches(condition.when, requested):
            continue
        missing = [name for name in condition.require if requested.get(name) is None]
        if missing:
            raise InvalidOptionCombinationError(
                "when " + ", ".join(f"{k}={v}" for k, v in condition.when.items())
                + " requires " + ", ".join(missing),
                details={"requires": missing, "when": condition.when},
            )
        forbidden = [name for name in condition.forbid if requested.get(name) is not None]
        if forbidden:
            raise InvalidOptionCombinationError(
                "when " + ", ".join(f"{k}={v}" for k, v in condition.when.items())
                + " forbids " + ", ".join(forbidden),
                details={"forbidden": forbidden, "when": condition.when},
            )
        for name, allowed in condition.allowed.items():
            if requested.get(name) is not None and requested[name] not in allowed:
                raise InvalidOptionCombinationError(
                    f"{name}={requested[name]!r} is not allowed when "
                    + ", ".join(f"{k}={v}" for k, v in condition.when.items()),
                    details={"option": name, "allowed": allowed, "when": condition.when},
                )


def _when_matches(when: dict[str, Any], requested: dict[str, Any]) -> bool:
    return all(requested.get(key) == value for key, value in when.items())


class CapabilityValidator:
    """Validates one V3 capability request against one :class:`CapabilitySpec`."""

    def validate(
        self,
        request: Any,
        spec: CapabilitySpec,
        *,
        resolved_references: list[ResolvedReference] | None = None,
    ) -> None:
        _validate_input_slots(request, spec, resolved_references=resolved_references)
        _validate_options(request, spec)
        _validate_constraints(request, spec)
