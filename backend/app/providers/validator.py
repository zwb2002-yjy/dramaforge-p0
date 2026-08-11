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
    UnsupportedOptionError,
)
from app.providers.manifest import CapabilitySpec, InputSlotSpec

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
    """Per-input-slot artifact counts for a V3 capability request."""
    counts: dict[str, int] = {}
    if isinstance(request, ImageToVideoRequest):
        counts["first_frame"] = 1
    elif isinstance(request, FirstLastFrameVideoRequest):
        counts["first_frame"] = 1
        counts["last_frame"] = 1
    elif isinstance(request, ReferenceToVideoRequest):
        counts["reference_images"] = len(request.reference_images)
        counts["reference_audio"] = len(request.reference_audio)
        counts["reference_videos"] = len(request.reference_videos)
    elif isinstance(request, ImageGenerateRequest):
        counts["reference_image"] = len(request.reference_images)
    return counts


def _requested_options(request: Any) -> dict[str, Any]:
    if not isinstance(request, BaseModel):
        return {}
    return {
        key: value
        for key, value in request.model_dump(exclude_unset=False).items()
        if key in _COMMON_OPTION_FIELDS and value is not None
    }


def _validate_input_slots(request: Any, spec: CapabilitySpec) -> None:
    counts = _role_counts(request)
    for role, count in counts.items():
        slot = spec.input_slots.get(role)
        if slot is None:
            # A reference role the model does not declare means the capability
            # itself is not satisfied (the selector gate already guards this).
            continue
        _check_slot(slot, role, count)
    # Required slots must be present.
    for role, slot in spec.input_slots.items():
        if slot.required and counts.get(role, 0) < 1:
            raise InvalidOptionCombinationError(
                f"required input slot is missing: {role}",
                details={"slot": role},
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
        if declared.enum and value not in declared.enum:
            raise UnsupportedOptionError(
                option,
                message=f"{option}={value!r} is not one of {declared.enum}",
            )
    for option in dict(getattr(request, "native_options", {}) or {}):
        if option not in spec.native_options:
            raise UnsupportedOptionError(option)


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

    def validate(self, request: Any, spec: CapabilitySpec) -> None:
        _validate_input_slots(request, spec)
        _validate_options(request, spec)
        _validate_constraints(request, spec)
