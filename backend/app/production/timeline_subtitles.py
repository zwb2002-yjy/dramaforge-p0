"""One deterministic millisecond map for final Timeline render and subtitle cues."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol


class TimelineTimingError(ValueError):
    pass


class TimedClip(Protocol):
    @property
    def clip_id(self) -> str: ...
    @property
    def subtitle_text(self) -> str: ...
    @property
    def source_in_seconds(self) -> float: ...
    @property
    def duration_seconds(self) -> float: ...
    @property
    def source_out_seconds(self) -> float | None: ...
    @property
    def transition_kind(self) -> str | None: ...
    @property
    def transition_duration_seconds(self) -> float: ...


@dataclass(frozen=True)
class ClipTiming:
    clip_id: str
    start_ms: int
    end_ms: int
    source_in_ms: int
    source_out_ms: int
    duration_ms: int
    overlap_ms: int


@dataclass(frozen=True)
class TimelineSubtitleMap:
    clips: tuple[ClipTiming, ...]
    duration_ms: int
    cue_count: int
    srt_bytes: bytes

    def evidence(self) -> list[dict[str, object]]:
        return [asdict(clip) for clip in self.clips]


def _milliseconds(value: float) -> int:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise TimelineTimingError("Timeline times must be finite and nonnegative")
    return int((number * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _timestamp(milliseconds: int) -> str:
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_timeline_subtitles(clips: Sequence[TimedClip]) -> TimelineSubtitleMap:
    if not clips:
        raise TimelineTimingError("Timeline has no clips")
    timings: list[ClipTiming] = []
    cues: list[str] = []
    end = 0
    seen: set[str] = set()
    for index, clip in enumerate(clips):
        if not clip.clip_id or clip.clip_id in seen:
            raise TimelineTimingError("Timeline clip ids must be unique and nonempty")
        seen.add(clip.clip_id)
        duration = _milliseconds(clip.duration_seconds)
        source_in = _milliseconds(clip.source_in_seconds)
        source_out = (
            _milliseconds(clip.source_out_seconds)
            if clip.source_out_seconds is not None
            else source_in + duration
        )
        if source_out <= source_in:
            raise TimelineTimingError("Source out must follow source in")
        if duration < 1:
            raise TimelineTimingError("Timeline clips must last at least one millisecond")
        if clip.transition_kind not in {None, "cut", "crossfade"}:
            raise TimelineTimingError("Unsupported Timeline transition")
        overlap = (
            _milliseconds(clip.transition_duration_seconds)
            if index > 0 and clip.transition_kind == "crossfade"
            else 0
        )
        if (
            index > 0
            and clip.transition_kind == "crossfade"
            and not 0 < overlap < min(timings[-1].duration_ms, duration)
        ):
            raise TimelineTimingError("Crossfade must be shorter than both adjacent clips")
        start = end - overlap
        end = start + duration
        timings.append(
            ClipTiming(clip.clip_id, start, end, source_in, source_out, duration, overlap)
        )
        # Empty lines delimit cues in SRT; retain all nonempty Unicode lines
        # without accidentally emitting another cue or resurrecting old dialogue.
        text = "\n".join(
            line
            for line in clip.subtitle_text.replace("\r\n", "\n")
            .replace("\r", "\n")
            .strip()
            .split("\n")
            if line.strip()
        )
        if text:
            cues.append(f"{len(cues) + 1}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}\n")
    return TimelineSubtitleMap(tuple(timings), end, len(cues), "\n".join(cues).encode("utf-8"))
