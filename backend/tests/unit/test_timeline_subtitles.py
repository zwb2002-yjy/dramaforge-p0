"""Final subtitles derive from the same bounded Timeline clock as FFmpeg."""

from __future__ import annotations

from dataclasses import asdict, replace

import pytest
from app.production.timeline_renderer import TimelineRenderClip, render_timeline
from app.production.timeline_subtitles import (
    TimelineClipInstructions,
    TimelineTimingError,
    build_timeline_subtitles,
)


def clip(key="one", **changes):
    return replace(
        TimelineClipInstructions(
            clip_id=key,
            video_artifact_id=key,
            subtitle_text="第一行\nSecond line",
            source_in_seconds=1.25,
            duration_seconds=2.0,
        ),
        **changes,
    )


def test_reordered_trimmed_crossfade_and_cuts_share_one_clock():
    result = build_timeline_subtitles(
        [
            clip("B"),
            clip("A", transition_kind="crossfade", transition_duration_seconds=0.5),
            clip("C", subtitle_text="", transition_kind="cut", transition_duration_seconds=1),
        ]
    )
    assert [(item.start_ms, item.end_ms) for item in result.clips] == [
        (0, 2000),
        (1500, 3500),
        (3500, 5500),
    ]
    assert result.duration_ms == 5500 and result.cue_count == 2
    assert result.clips[0].source_in_ms == 1250
    text = result.srt_bytes.decode("utf-8")
    assert "00:00:01,500 --> 00:00:03,500" in text
    assert text.count("第一行\nSecond line") == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_seconds": 0},
        {"duration_seconds": float("nan")},
        {"source_in_seconds": -1},
        {"transition_kind": "unsupported"},
        {"transition_kind": "crossfade", "transition_duration_seconds": 2},
    ],
)
def test_invalid_timing_fails_closed(changes):
    with pytest.raises(TimelineTimingError):
        build_timeline_subtitles([clip(), clip("two", **changes)])


def test_empty_subtitles_do_not_create_a_fake_file():
    result = build_timeline_subtitles([clip(subtitle_text="\r\n  ")])
    assert result.srt_bytes == b"" and result.cue_count == 0


@pytest.mark.asyncio
async def test_test_renderer_duration_matches_real_crossfade_map(tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    result = await render_timeline(
        [
            TimelineRenderClip(**asdict(item), video_path=video)
            for item in [
                clip(),
                clip("two", transition_kind="crossfade", transition_duration_seconds=0.5),
            ]
        ],
        lineage="same",
        output_path=tmp_path / "final.mp4",
    )
    assert result.ffprobe["format"]["duration"] == "3.500"
    assert result.summary["timeline_time_map"][1]["start_ms"] == 1500
    assert b"00:00:01,500 --> 00:00:03,500" in result.subtitle_data
