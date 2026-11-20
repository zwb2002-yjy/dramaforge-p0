"""Turn a frozen edit-session document into render instructions (I9-02).

The renderer itself is FFmpeg and lives in ``app.production.timeline_renderer``;
this module owns the *seam*: it reads one frozen session version and produces the
exact ordered clip instructions plus subtitle bytes that the render job will
consume. It never queries production truth (the clip's frozen artifact identity is
already in the document) and never writes anything.

That keeps the later render honest: an export can only be produced from a plan
built out of one immutable version, and the same plan recomputes the same SRT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.production.timeline_subtitles import (
    TimelineClipInstructions,
    TimelineTimingError,
    build_timeline_subtitles,
)
from app.shared.errors import ValidationAppError


@dataclass(frozen=True)
class EditRenderPlan:
    edit_session_id: UUID
    timeline_version: int
    timeline_hash: str
    episode_id: UUID | None
    instructions: tuple[TimelineClipInstructions, ...]
    duration_ms: int
    srt_bytes: bytes

    def summary(self) -> dict[str, Any]:
        return {
            "edit_session_id": str(self.edit_session_id),
            "timeline_version": self.timeline_version,
            "timeline_hash": self.timeline_hash,
            "episode_id": str(self.episode_id) if self.episode_id else None,
            "clip_count": len(self.instructions),
            "duration_ms": self.duration_ms,
            "subtitle_bytes": len(self.srt_bytes),
        }


def _invalid(code: str, **details: object) -> ValidationAppError:
    return ValidationAppError(
        "the frozen timeline cannot be rendered", details={"code": code, **details}
    )


def _frozen_artifact(clip: dict[str, Any]) -> str:
    snapshot = clip.get("selection_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("artifact_id"), str):
        return str(snapshot["artifact_id"])
    raw = clip.get("artifact_id")
    if isinstance(raw, str):
        return raw
    return ""


def _transition(clip: dict[str, Any]) -> tuple[str | None, float]:
    raw = clip.get("transition")
    if not isinstance(raw, dict):
        return None, 0.0
    kind = raw.get("kind")
    duration = raw.get("duration_seconds", 0.0)
    if not isinstance(kind, str) or not kind:
        return None, 0.0
    try:
        value = float(duration)
    except (TypeError, ValueError):
        return kind, 0.0
    return kind, max(0.0, value)


def build_render_plan(
    *,
    edit_session_id: UUID,
    timeline_version: int,
    timeline_hash: str,
    episode_id: UUID | None,
    document: dict[str, Any],
) -> EditRenderPlan:
    """Build the ordered instructions for one frozen session version."""
    raw_clips = document.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise _invalid("RENDER_PLAN_EMPTY")
    ordered = sorted(
        (clip for clip in raw_clips if isinstance(clip, dict)),
        key=lambda clip: int(clip.get("order") or 0),
    )
    if len(ordered) != len(raw_clips):
        raise _invalid("RENDER_PLAN_INVALID")
    orders = [int(clip.get("order") or 0) for clip in ordered]
    if orders != list(range(1, len(ordered) + 1)):
        raise _invalid("RENDER_PLAN_INVALID")

    instructions: list[TimelineClipInstructions] = []
    for clip in ordered:
        artifact_id = _frozen_artifact(clip)
        if not artifact_id:
            raise _invalid("RENDER_CLIP_UNBOUND", clip_id=str(clip.get("id") or ""))
        clip_id = str(clip.get("id") or "")
        if not clip_id:
            raise _invalid("RENDER_PLAN_INVALID")
        try:
            duration = float(clip.get("duration_seconds", 0.0))
        except (TypeError, ValueError) as exc:
            raise _invalid("RENDER_PLAN_INVALID", clip_id=clip_id) from exc
        if duration <= 0:
            # A zero-length clip cannot be cut or subtitled; refuse rather than
            # silently dropping it from the film.
            raise _invalid("RENDER_CLIP_EMPTY", clip_id=clip_id)
        kind, transition_seconds = _transition(clip)
        instructions.append(
            TimelineClipInstructions(
                clip_id=clip_id,
                video_artifact_id=artifact_id,
                subtitle_text=str(clip.get("subtitle") or ""),
                source_in_seconds=0.0,
                duration_seconds=duration,
                transition_kind=kind,
                transition_duration_seconds=transition_seconds,
            )
        )
    try:
        subtitles = build_timeline_subtitles(instructions)
    except TimelineTimingError as exc:
        raise _invalid("RENDER_PLAN_INVALID") from exc
    return EditRenderPlan(
        edit_session_id=edit_session_id,
        timeline_version=timeline_version,
        timeline_hash=timeline_hash,
        episode_id=episode_id,
        instructions=tuple(instructions),
        duration_ms=subtitles.duration_ms,
        srt_bytes=subtitles.srt_bytes,
    )


__all__ = ["EditRenderPlan", "build_render_plan"]
