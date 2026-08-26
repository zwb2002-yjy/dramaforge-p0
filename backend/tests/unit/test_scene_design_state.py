"""P1-02 SceneDesignState schema contract."""

from __future__ import annotations

from app.assets.schemas import SceneDesignState


def test_scene_design_state_defaults_are_serializable() -> None:
    state = SceneDesignState()
    assert state.model_dump() == {
        "visual_override": {},
        "continuity_rules": [],
        "role_states": [],
        "key_props": [],
        "layout_spec": {},
        "blocking_2d": {},
        "blocking_3d": {},
    }


def test_scene_design_state_round_trips_structured_values() -> None:
    payload = {
        "visual_override": {"palette": ["#111", "#eee"]},
        "continuity_rules": [{"role": "lead", "rule": "keep left"}],
        "role_states": [{"role": "lead", "state": "seated"}],
        "key_props": [{"name": "door", "location": "entry"}],
        "layout_spec": {"units": "project-scene"},
        "blocking_2d": {"lead": {"x": 0.2, "y": 0.3}},
        "blocking_3d": {"lead": {"x": 0.2, "y": 0.3, "z": 0.0}},
    }
    state = SceneDesignState.model_validate(payload)
    assert state.model_dump() == payload
