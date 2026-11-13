"""Validation of current Episode/Scene planning payloads."""

import pytest
from app.director.workflows.layered_planning import (
    EpisodePlanPayload,
    ScenePlanPayload,
    SceneStoryboardPlanPayload,
    ShotPlanPayload,
)


def test_episode_plan_rejects_too_few_scenes() -> None:
    with pytest.raises(ValueError):
        EpisodePlanPayload(episode_number=1, title="X", target_duration=60.0, scenes=[])


def test_episode_plan_rejects_duplicate_scene_numbers() -> None:
    with pytest.raises(ValueError):
        EpisodePlanPayload(
            episode_number=1, title="X", target_duration=60.0,
            scenes=[
                ScenePlanPayload(scene_number=1, location="A", time_of_day="day",
                                 estimated_duration=10),
                ScenePlanPayload(scene_number=1, location="B", time_of_day="day",
                                 estimated_duration=10),
            ],
        )


def test_scene_storyboard_rejects_shot_count_and_duplicates() -> None:
    with pytest.raises(ValueError):
        SceneStoryboardPlanPayload(shots=[])
    with pytest.raises(ValueError):
        SceneStoryboardPlanPayload(shots=[
            ShotPlanPayload(shot_number=1, visual_description="a"),
            ShotPlanPayload(shot_number=1, visual_description="b"),
        ])
