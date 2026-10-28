"""Shared, validated projection of compiler options and actual non-media Wire."""

from __future__ import annotations

import math
import re
from typing import Any, cast

from pydantic import JsonValue

from app.providers.translation import RequestTransformation

_COMPILER_AUDIT_OPTION_FIELDS = frozenset(
    {"aspect_ratio", "duration_seconds", "resolution", "generate_audio", "seed", "size"}
)
_COMPILER_AUDIT_REASON_CODES = frozenset(
    {
        "provider_inherits_aspect_ratio_from_first_frame",
        "provider_applies_documented_default",
        "frozen_manifest_native_size_tier",
    }
)


def _same_option(left: object, right: object) -> bool:
    return left == right and isinstance(left, bool) == isinstance(right, bool)


def compiler_option_evidence(
    compiled: object,
) -> tuple[dict[str, Any] | None, list[RequestTransformation]]:
    """Read a deliberately small, secret-free compiler audit envelope.

    Existing compilers which do not publish the envelope retain their current
    translation behavior.  A compiler which does publish it must conform to
    this allowlisted scalar schema; malformed or unexpected data fails closed.
    """
    summary = getattr(compiled, "safe_request_summary", None)
    if not isinstance(summary, dict):
        return None, []
    has_effective = "effective_common_options" in summary
    has_transformations = "translation_transformations" in summary
    if not has_effective and not has_transformations:
        return None, []
    if not has_effective or not has_transformations:
        raise ValueError("compiler translation evidence is incomplete")

    raw_effective = summary["effective_common_options"]
    raw_transformations = summary["translation_transformations"]
    if not isinstance(raw_effective, dict) or not isinstance(raw_transformations, list):
        raise ValueError("compiler translation evidence has an invalid schema")

    def safe_value(field: str, value: object) -> bool:
        if value is None:
            return True
        if field in {"aspect_ratio", "resolution", "size"}:
            return isinstance(value, str) and 0 < len(value) <= 32
        if field == "duration_seconds":
            return (
                not isinstance(value, bool)
                and isinstance(value, int | float)
                and math.isfinite(value)
                and 0 < value <= 3600
            )
        if field == "generate_audio":
            return isinstance(value, bool)
        if field == "seed":
            return (
                not isinstance(value, bool) and isinstance(value, int) and -(2**63) <= value < 2**63
            )
        return False

    effective: dict[str, Any] = {}
    for key, value in raw_effective.items():
        if (
            not isinstance(key, str)
            or key not in _COMPILER_AUDIT_OPTION_FIELDS
            or not safe_value(key, value)
        ):
            raise ValueError("compiler effective options are not safe common options")
        effective[key] = value

    transformations: list[RequestTransformation] = []
    for raw in raw_transformations:
        if not isinstance(raw, dict) or set(raw) != {
            "field",
            "from_value",
            "to_value",
            "reason",
        }:
            raise ValueError("compiler transformation has an invalid schema")
        field = raw["field"]
        reason = raw["reason"]
        if (
            not isinstance(field, str)
            or field not in _COMPILER_AUDIT_OPTION_FIELDS
            or not isinstance(reason, str)
            or reason not in _COMPILER_AUDIT_REASON_CODES
            or not safe_value(field, raw["from_value"])
            or not safe_value(field, raw["to_value"])
        ):
            raise ValueError("compiler transformation is not safe audit evidence")
        transformations.append(RequestTransformation.model_validate(raw))
    return effective, transformations


def compiled_generation_evidence(
    compiled: object,
) -> tuple[dict[str, JsonValue], list[RequestTransformation]]:
    """Use actual Wire and compiler-declared transformations, never caller options."""
    body = getattr(compiled, "wire_request", None)
    if not isinstance(body, dict):
        raise ValueError("compiler has no Wire request")
    is_video = getattr(compiled, "operation", "").startswith("video")
    aliases = {
        "ratio": "aspect_ratio",
        "duration": "duration_seconds",
        "seconds": "duration_seconds",
    }
    if is_video:
        aliases["size"] = "resolution"
    allowed = _COMPILER_AUDIT_OPTION_FIELDS | {
        "width",
        "height",
        "num_frames",
        "frame_rate",
        "n",
        "watermark",
        "aigc_watermark",
        "prompt_optimizer",
    }
    wire: dict[str, JsonValue] = {}
    for key, value in body.items():
        name = aliases.get(key, key)
        if name not in allowed or value is None:
            continue
        if key == "seconds" and isinstance(value, str) and value.isdecimal():
            value = int(value)
        safe_string = isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9.:_-]{1,64}", value)
        if (
            safe_string
            or isinstance(value, bool | int)
            or (isinstance(value, float) and math.isfinite(value))
        ):
            wire[name] = value

    target = body.get("target")
    if getattr(compiled, "provider_type", None) == "openai_compatible_media" and isinstance(
        target, dict
    ):
        for name in ("aspect_ratio", "duration_seconds"):
            value = target.get(name)
            if value is None:
                continue
            if name in wire and wire[name] != value:
                raise ValueError("Wire target conflicts with top-level output")
            if isinstance(value, str | int | float) and not isinstance(value, bool):
                wire[name] = value

    # Only this installed protocol defines duration as (frames - 1) / fps.
    if getattr(compiled, "provider_type", None) == "agnes" and is_video:
        frames, fps = body.get("num_frames"), body.get("frame_rate")
        if type(frames) is int and type(fps) is int and frames > 1 and fps > 0:
            wire["duration_seconds"] = (frames - 1) / fps
    width, height = body.get("width"), body.get("height")
    size = body.get("size")
    if isinstance(size, str) and re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", size):
        width, height = (int(value) for value in size.split("x"))
    if type(width) is int and type(height) is int and width > 0 and height > 0:
        divisor = math.gcd(width, height)
        wire.setdefault("aspect_ratio", f"{width // divisor}:{height // divisor}")
    declared, transformations = compiler_option_evidence(compiled)
    if declared is None:
        return wire, transformations
    effective = dict(declared)
    for transformation in transformations:
        effective[transformation.field] = transformation.to_value
    for name in effective.keys() & wire.keys():
        if effective[name] is not None and not _same_option(effective[name], wire[name]):
            raise ValueError("compiler option evidence conflicts with actual Wire")
    return {**cast(dict[str, JsonValue], effective), **wire}, transformations


def uncompiled_requested_options(
    requested: dict[str, JsonValue],
    effective: dict[str, JsonValue],
    transformations: list[RequestTransformation],
) -> list[str]:
    """An explicit field must be sent, derived, or have a declared conversion."""
    return sorted(
        name
        for name, value in requested.items()
        if value is not None
        and (
            name not in effective
            or not _same_option(effective[name], value)
            and not any(
                item.field == name
                and _same_option(item.from_value, value)
                and _same_option(item.to_value, effective[name])
                for item in transformations
            )
        )
    )
