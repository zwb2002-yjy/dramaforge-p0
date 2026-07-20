"""S4 local 10-shot mock production and partial subtitle rework."""

from __future__ import annotations

from app.execution.multi_shot import produce_shots, rework_subtitle_only
from app.execution.runtime_invariants import RuntimeState


def test_ten_shots_produced() -> None:
    shots = produce_shots(10)
    assert len(shots) == 10
    assert all(s.status == "review_passed" for s in shots)
    assert all("keyframe" in s.artifact_ids for s in shots)


def test_subtitle_rework_preserves_upstream_artifacts() -> None:
    shots = produce_shots(3)
    shot = shots[0]
    kf = shot.artifact_ids["keyframe"]
    vid = shot.artifact_ids["video"]
    voice = shot.artifact_ids["voice"]
    old_sub = shot.artifact_ids["subtitle"]
    state = RuntimeState(budget_remaining=50.0)
    # seed cache for unchanged upstream
    state.cache[f"{shot.shot_id}:keyframe:{shot.shot_id}:keyframe:v1"] = kf
    rework_subtitle_only(shot, "Reworked line", state)
    assert shot.artifact_ids["keyframe"] == kf
    assert shot.artifact_ids["video"] == vid
    assert shot.artifact_ids["voice"] == voice
    assert shot.artifact_ids["subtitle"] != old_sub
    assert shot.subtitle == "Reworked line"
