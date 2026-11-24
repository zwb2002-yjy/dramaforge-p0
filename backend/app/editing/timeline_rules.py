"""Editable clip audio rules shared by Save and export/preview compilation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from app.shared.errors import ValidationAppError


def clip_audio_volume(clip: Mapping[str, Any]) -> float:
    raw = clip.get("audio_volume", 1.0)
    try:
        if isinstance(raw, bool):
            raise ValueError("Boolean volume")
        volume = float(raw)
    except (ValueError, TypeError) as exc:
        raise ValidationAppError(
            "Timeline audio volume must be between zero and one",
            details={"code": "INVALID_TIMELINE_AUDIO_VOLUME"},
        ) from exc
    if not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ValidationAppError(
            "Timeline audio volume must be between zero and one",
            details={"code": "INVALID_TIMELINE_AUDIO_VOLUME"},
        )
    if not isinstance(clip.get("muted", False), bool):
        raise ValidationAppError(
            "Timeline muted must be boolean", details={"code": "INVALID_TIMELINE_MUTE"}
        )
    return volume


def timeline_number(value: object, *, default: float | None, code: str) -> float | None:
    if value is None:
        return default
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValidationAppError(
            "Timeline numeric field is invalid", details={"code": code}
        ) from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise ValidationAppError("Timeline numeric field is not finite", details={"code": code})
    return result


def clip_transition(value: object) -> tuple[str | None, float]:
    if value is None:
        return None, 0.0
    if isinstance(value, str):
        kind = value.strip().lower()
        duration = 0.25 if kind == "crossfade" else 0.0
    elif isinstance(value, dict):
        kind = str(value.get("kind") or value.get("type") or "cut").strip().lower()
        duration = (
            timeline_number(
                value.get("duration_seconds"),
                default=0.25 if kind == "crossfade" else 0.0,
                code="INVALID_TIMELINE_TRANSITION_DURATION",
            )
            or 0.0
        )
    else:
        raise ValidationAppError(
            "Timeline transition must be a string or object",
            details={"code": "INVALID_TIMELINE_TRANSITION"},
        )
    if kind not in {"cut", "crossfade"}:
        raise ValidationAppError(
            f"unsupported Timeline transition: {kind}",
            details={"code": "UNSUPPORTED_TIMELINE_TRANSITION"},
        )
    if duration < 0:
        raise ValidationAppError(
            "Timeline transition duration must be non-negative",
            details={"code": "INVALID_TIMELINE_TRANSITION_DURATION"},
        )
    return kind, duration
