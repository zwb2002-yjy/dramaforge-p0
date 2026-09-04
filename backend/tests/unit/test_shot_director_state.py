"""P1-02 ShotDirectorState schema contract."""

from __future__ import annotations

from app.assets.schemas import ShotDirectorState


def test_shot_director_state_defaults_are_serializable() -> None:
    state = ShotDirectorState()
    assert state.model_dump() == {
        "framing": {"shot_size": "", "angle": ""},
        "camera": {"movement": "", "focal_length_mm": None},
        "action": {"description": ""},
        "expression": {},
        "gaze": {"target_type": "", "target": ""},
        "composition": {"description": ""},
        "continuity_constraints": [],
        "model_overrides": {"image_model_id": None, "video_model_id": None},
        "video_reference_risk": None,
    }


def test_shot_director_state_round_trips_design_example() -> None:
    payload = {
        "framing": {"shot_size": "close_up", "angle": "eye_level"},
        "camera": {"movement": "locked", "focal_length_mm": 50},
        "action": {"description": "缓慢回头看向门口"},
        "expression": {"emotion": "surprised"},
        "gaze": {"target_type": "point", "target": "door"},
        "composition": {"description": "rule of thirds"},
        "continuity_constraints": [{"kind": "screen_direction", "value": "right"}],
        "model_overrides": {"image_model_id": None, "video_model_id": "provider/video-x"},
        "video_reference_risk": {"level": "low"},
    }
    state = ShotDirectorState.model_validate(payload)
    assert state.model_dump() == payload
