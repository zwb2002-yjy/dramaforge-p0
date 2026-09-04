"""Pydantic schemas for professional workspace asset states."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SceneDesignState(BaseModel):
    """Serialized professional scene design state.

    This is the single source for scene-level visual overrides, continuity
    rules, role states, key props, layout, and 2D/3D blocking.  It must not
    store Three.js runtime objects or other non-serializable values.
    """

    visual_override: dict[str, object] = Field(default_factory=dict)
    continuity_rules: list[dict[str, object]] = Field(default_factory=list)
    role_states: list[dict[str, object]] = Field(default_factory=list)
    key_props: list[dict[str, object]] = Field(default_factory=list)
    layout_spec: dict[str, object] = Field(default_factory=dict)
    blocking_2d: dict[str, object] = Field(default_factory=dict)
    blocking_3d: dict[str, object] = Field(default_factory=dict)


class ShotFramingState(BaseModel):
    shot_size: str = Field(default="", max_length=40)
    angle: str = Field(default="", max_length=40)


class ShotCameraState(BaseModel):
    movement: str = Field(default="", max_length=80)
    focal_length_mm: int | None = Field(default=None, ge=1, le=2000)


class ShotActionState(BaseModel):
    description: str = Field(default="", max_length=2000)


class ShotGazeState(BaseModel):
    target_type: str = Field(default="", max_length=40)
    target: str = Field(default="", max_length=200)


class ShotCompositionState(BaseModel):
    description: str = Field(default="", max_length=2000)


class ShotModelOverrides(BaseModel):
    image_model_id: str | None = Field(default=None, max_length=240)
    video_model_id: str | None = Field(default=None, max_length=240)


class ShotDirectorState(BaseModel):
    """Serialized professional shot director intent.

    Kept separate from the free-text prompts (`image_prompt`, `video_prompt`)
    so that structured camera, framing, action, and continuity semantics can
    be validated, diffed, and translated to model controls independently.
    """

    framing: ShotFramingState = Field(default_factory=ShotFramingState)
    camera: ShotCameraState = Field(default_factory=ShotCameraState)
    action: ShotActionState = Field(default_factory=ShotActionState)
    expression: dict[str, object] = Field(default_factory=dict)
    gaze: ShotGazeState = Field(default_factory=ShotGazeState)
    composition: ShotCompositionState = Field(default_factory=ShotCompositionState)
    continuity_constraints: list[dict[str, object]] = Field(default_factory=list)
    model_overrides: ShotModelOverrides = Field(default_factory=ShotModelOverrides)
    video_reference_risk: dict[str, object] | None = Field(default=None)
