"""Editable clip audio rules shared by Save and export/preview compilation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

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
