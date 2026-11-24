"""A render plan is derived from exactly one frozen timeline version (I9-02)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.production.edit_render_plan import build_render_plan
from app.shared.errors import ValidationAppError


def _clip(*, order: int, artifact: str, subtitle: str = "", duration: float = 5.0):
    return {
        "id": f"clip-{order}",
        "order": order,
        "duration_seconds": duration,
        "subtitle": subtitle,
        "transition": None,
        "selection_snapshot": {"artifact_id": artifact, "timeline_version": 2},
    }


def _plan(clips: list[dict], **overrides):
    payload = {
        "edit_session_id": uuid4(),
        "timeline_version": 2,
        "timeline_hash": "a" * 64,
        "episode_id": None,
        "document": {"schema_version": 2, "clips": clips, "metadata": {}},
    }
    payload.update(overrides)
    return build_render_plan(**payload)


def test_plan_orders_clips_and_produces_subtitles() -> None:
    first = str(uuid4())
    second = str(uuid4())
    plan = _plan(
        [
            _clip(order=2, artifact=second, subtitle="第二句"),
            _clip(order=1, artifact=first, subtitle="第一句"),
        ]
    )
    assert [item.clip_id for item in plan.instructions] == ["clip-1", "clip-2"]
    assert [item.video_artifact_id for item in plan.instructions] == [first, second]
    assert plan.duration_ms == 10_000
    text = plan.srt_bytes.decode("utf-8")
    assert "第一句" in text and "第二句" in text
    assert text.index("第一句") < text.index("第二句")
    assert plan.summary()["clip_count"] == 2


def test_identical_documents_produce_identical_subtitles() -> None:
    """The same frozen version must recompute the same bytes."""
    clips = [_clip(order=1, artifact=str(uuid4()), subtitle="同一句")]
    first = _plan(clips)
    second = _plan(clips)
    assert first.srt_bytes == second.srt_bytes
    assert first.duration_ms == second.duration_ms


def test_empty_or_gapped_clips_are_refused() -> None:
    with pytest.raises(ValidationAppError) as empty:
        _plan([])
    assert empty.value.details["code"] == "RENDER_PLAN_EMPTY"

    with pytest.raises(ValidationAppError) as gap:
        _plan([_clip(order=1, artifact=str(uuid4())), _clip(order=3, artifact=str(uuid4()))])
    assert gap.value.details["code"] == "RENDER_PLAN_INVALID"


def test_unbound_or_zero_length_clip_is_refused_not_dropped() -> None:
    unbound = _clip(order=1, artifact="")
    with pytest.raises(ValidationAppError) as missing:
        _plan([unbound])
    assert missing.value.details["code"] == "RENDER_CLIP_UNBOUND"

    empty_clip = _clip(order=1, artifact=str(uuid4()), duration=0.0)
    with pytest.raises(ValidationAppError) as zero:
        _plan([empty_clip])
    assert zero.value.details["code"] == "RENDER_CLIP_EMPTY"


def test_transition_is_carried_into_the_instructions() -> None:
    clip = _clip(order=1, artifact=str(uuid4()))
    clip["transition"] = {"kind": "crossfade", "duration_seconds": 0.5}
    plan = _plan([clip])
    assert plan.instructions[0].transition_kind == "crossfade"
    assert plan.instructions[0].transition_duration_seconds == 0.5


def test_render_plan_preserves_clip_trim_audio_and_disabled_subtitles() -> None:
    audio_id = str(uuid4())
    clip = _clip(order=1, artifact=str(uuid4()), subtitle="hidden")
    clip.update(
        source_in_seconds=2,
        source_out_seconds=6,
        audio_id=audio_id,
        audio_volume=0.5,
        subtitle_enabled=False,
    )
    plan = _plan([clip])
    item = plan.instructions[0]
    assert (item.source_in_seconds, item.source_out_seconds) == (2, 6)
    assert (item.audio_artifact_id, item.audio_volume) == (audio_id, 0.5)
    assert plan.srt_bytes == b""
    clip["muted"] = True
    assert _plan([clip]).instructions[0].audio_artifact_id is None
