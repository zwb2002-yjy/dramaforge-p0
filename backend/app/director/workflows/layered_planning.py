"""Layered story planning contracts + safety limits (WF8).

Replaces the "single 15-30s / 3-6 shot short" top-level constraint with layered
Episode→Scene→Shot planning.  Duration is owned by a Production Profile /
Workflow Template, and the shot/scene counts are platform safety limits defined
here (never scattered hard-codes).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Platform safety limits (V1.5). Business templates can be narrower.
PLATFORM_MIN_SHOTS_PER_SCENE = 1
PLATFORM_MAX_SHOTS_PER_SCENE = 24
PLATFORM_MIN_SCENES_PER_EPISODE = 1
PLATFORM_MAX_SCENES_PER_EPISODE = 20
PLATFORM_MIN_CHARACTERS_PER_SCENE = 0
PLATFORM_MAX_CHARACTERS_PER_SCENE = 8


class ProductionProfile(StrEnum):
    LIVE_ACTION_DIALOGUE_SHORT = "live_action_dialogue_short_v1"
    SHORT_DRAMA_EPISODE = "short_drama_episode_v1"
    COMIC_EPISODE = "comic_episode_v1"


# Duration range per production profile (seconds).
PRODUCTION_PROFILE_DURATION: dict[ProductionProfile, tuple[float, float]] = {
    ProductionProfile.LIVE_ACTION_DIALOGUE_SHORT: (15.0, 30.0),
    ProductionProfile.SHORT_DRAMA_EPISODE: (30.0, 180.0),
    ProductionProfile.COMIC_EPISODE: (30.0, 300.0),
}


class ShotPlanPayload(BaseModel):
    """One shot in a scene storyboard (planning shape, not execution)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shot_id: UUID | None = None
    shot_number: int = Field(ge=1)
    shot_type: str = "medium"
    camera_move: str = "static"
    visual_description: str = Field(min_length=1)
    dialogue: str = ""
    duration_seconds: float = Field(ge=0.5)
    template_key: str | None = None
    sort_order: int = Field(default=1, ge=1)


class ScenePlanPayload(BaseModel):
    """One scene plan inside an episode plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID | None = None
    scene_number: int = Field(ge=1)
    location: str = Field(min_length=1, max_length=160)
    time_of_day: str = Field(min_length=1, max_length=40)
    scene_goal: str = ""
    conflict: str = ""
    entry_state: str = ""
    exit_state: str = ""
    estimated_duration: float = Field(ge=0.0)
    characters: list[UUID] = Field(default_factory=list)
    continuity_requirements: list[str] = Field(default_factory=list)


class EpisodePlanPayload(BaseModel):
    """Full episode plan; materialize() turns it into a real Episode + Scenes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: UUID | None = None
    episode_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    target_duration: float = Field(ge=0.0)
    story_goal: str = ""
    opening_hook: str = ""
    turning_points: list[str] = Field(default_factory=list)
    ending_hook: str = ""
    production_profile: ProductionProfile = ProductionProfile.SHORT_DRAMA_EPISODE
    scenes: list[ScenePlanPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_episode_plan(self) -> EpisodePlanPayload:
        scene_count = len(self.scenes)
        if not (PLATFORM_MIN_SCENES_PER_EPISODE <= scene_count <= PLATFORM_MAX_SCENES_PER_EPISODE):
            raise ValueError(
                f"episode has {scene_count} scenes; platform safety limit is "
                f"[{PLATFORM_MIN_SCENES_PER_EPISODE}, {PLATFORM_MAX_SCENES_PER_EPISODE}]"
            )
        min_dur, max_dur = PRODUCTION_PROFILE_DURATION[self.production_profile]
        if not (min_dur <= self.target_duration <= max_dur):
            raise ValueError(
                f"episode target_duration {self.target_duration}s outside "
                f"profile {self.production_profile.value} range [{min_dur}, {max_dur}]"
            )
        numbers = [scene.scene_number for scene in self.scenes]
        if len(numbers) != len(set(numbers)):
            raise ValueError("episode scene numbers must be unique")
        return self


class SceneStoryboardPlanPayload(BaseModel):
    """Materializes real Shots for one scene (planning shape)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID | None = None
    template_profile: str = ""
    production_profile: ProductionProfile = ProductionProfile.SHORT_DRAMA_EPISODE
    shots: list[ShotPlanPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scene_storyboard(self) -> SceneStoryboardPlanPayload:
        if not (
            PLATFORM_MIN_SHOTS_PER_SCENE <= len(self.shots) <= PLATFORM_MAX_SHOTS_PER_SCENE
        ):
            raise ValueError(
                f"scene has {len(self.shots)} shots; platform safety limit is "
                f"[{PLATFORM_MIN_SHOTS_PER_SCENE}, {PLATFORM_MAX_SHOTS_PER_SCENE}]"
            )
        numbers = [shot.shot_number for shot in self.shots]
        if len(numbers) != len(set(numbers)):
            raise ValueError("scene shot numbers must be unique")
        return self
