"""Complex shot director intent + risk assessment (WF7).

``ShotDirectorIntent`` captures professional camera/blocking/motion intent; it is
stored in ``Shot.director_state`` (JSON), never split into DB columns.

``ShotComplexityAssessment`` uses deterministic rules (no LLM, no provider) to
classify a shot as ``SINGLE_PASS`` / ``STAGED`` / ``NEEDS_EXPERIMENT`` /
``UNSUPPORTED``.  A Director Agent may suggest, but cannot override a
deterministic blocker.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.director.workflows.character_participation import (
    MAX_VISIBLE_CONTROLLED_CHARACTERS,
    ShotParticipationPlan,
)


class CameraMotion(StrEnum):
    STATIC = "static"
    PUSH_IN = "push_in"
    PULL_OUT = "pull_out"
    PAN = "pan"
    TRACKING = "tracking"
    DOLLY = "dolly"
    HANDHELD = "handheld"


class ShotDirectorIntent(BaseModel):
    """Professional director intent for one shot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    shot_size: str = "medium"
    camera_angle: str = "eye_level"
    camera_height: str = "chest"
    lens_intent: str = "natural"
    camera_motion: CameraMotion = CameraMotion.STATIC
    subject_blocking: list[str] = Field(default_factory=list)
    subject_motion: list[str] = Field(default_factory=list)
    composition: str = ""
    focus_strategy: str = ""
    depth_strategy: str = ""
    action_beats: list[str] = Field(default_factory=list)
    dialogue_beats: list[str] = Field(default_factory=list)
    continuity_requirements: list[str] = Field(default_factory=list)

    @property
    def has_camera_motion(self) -> bool:
        return self.camera_motion is not CameraMotion.STATIC

    @property
    def has_physical_interaction(self) -> bool:
        return bool(self.subject_blocking) or bool(self.subject_motion)


class ComplexityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ComplexityStrategy(StrEnum):
    SINGLE_PASS = "SINGLE_PASS"
    STAGED = "STAGED"
    NEEDS_EXPERIMENT = "NEEDS_EXPERIMENT"
    UNSUPPORTED = "UNSUPPORTED"


class ShotComplexityAssessment(BaseModel):
    """Deterministic complexity / strategy classification for a shot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    character_count: int
    interaction_complexity: ComplexityLevel
    motion_complexity: ComplexityLevel
    camera_complexity: ComplexityLevel
    identity_risk: ComplexityLevel
    continuity_risk: ComplexityLevel
    strategy: ComplexityStrategy
    reasons: list[str] = Field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return self.strategy is ComplexityStrategy.UNSUPPORTED


def _level_from_count(count: int) -> ComplexityLevel:
    if count == 0:
        return ComplexityLevel.LOW
    if count <= 2:
        return ComplexityLevel.MEDIUM
    return ComplexityLevel.HIGH


def assess_shot_complexity(
    *,
    intent: ShotDirectorIntent,
    participation_plan: ShotParticipationPlan,
) -> ShotComplexityAssessment:
    """Deterministic complexity/strategy classification."""
    visible_count = participation_plan.visible_controlled_count
    reasons: list[str] = []

    if visible_count > MAX_VISIBLE_CONTROLLED_CHARACTERS:
        return ShotComplexityAssessment(
            character_count=visible_count,
            interaction_complexity=ComplexityLevel.HIGH,
            motion_complexity=ComplexityLevel.HIGH,
            camera_complexity=ComplexityLevel.HIGH,
            identity_risk=ComplexityLevel.HIGH,
            continuity_risk=ComplexityLevel.HIGH,
            strategy=ComplexityStrategy.UNSUPPORTED,
            reasons=[f"visible controlled characters exceed {MAX_VISIBLE_CONTROLLED_CHARACTERS}"],
        )

    interaction = ComplexityLevel.HIGH if intent.has_physical_interaction else ComplexityLevel.LOW
    motion = (
        ComplexityLevel.HIGH
        if (intent.has_physical_interaction or intent.subject_motion)
        else ComplexityLevel.LOW
    )
    high_camera_motions = {
        CameraMotion.TRACKING,
        CameraMotion.HANDHELD,
        CameraMotion.DOLLY,
    }
    camera = (
        ComplexityLevel.HIGH
        if intent.camera_motion in high_camera_motions
        else (ComplexityLevel.MEDIUM if intent.has_camera_motion else ComplexityLevel.LOW)
    )
    identity_risk = _level_from_count(visible_count)
    continuity_risk = (
        ComplexityLevel.HIGH
        if (intent.continuity_requirements or intent.has_camera_motion)
        else ComplexityLevel.MEDIUM
    )

    # Deterministic strategy (an Agent may suggest, never override).
    if visible_count >= 3 and (
        interaction is ComplexityLevel.HIGH or camera is ComplexityLevel.HIGH
    ):
        strategy = ComplexityStrategy.NEEDS_EXPERIMENT
        reasons.append(
            "multi-character with interaction/tracking camera: run an experiment "
            "before formal production"
        )
    elif visible_count >= 2 and (
        interaction is ComplexityLevel.HIGH or camera is ComplexityLevel.HIGH
    ):
        strategy = ComplexityStrategy.STAGED
        reasons.append(
            "two-character with interaction/camera motion: use a staged strategy"
        )
    elif visible_count >= 3:
        strategy = ComplexityStrategy.NEEDS_EXPERIMENT
        reasons.append("three or more visible characters: validate identity first")
    else:
        strategy = ComplexityStrategy.SINGLE_PASS
        reasons.append("low-risk shot; single-pass production is safe")

    return ShotComplexityAssessment(
        character_count=visible_count,
        interaction_complexity=interaction,
        motion_complexity=motion,
        camera_complexity=camera,
        identity_risk=identity_risk,
        continuity_risk=continuity_risk,
        strategy=strategy,
        reasons=reasons,
    )


def complexity_director_state(
    intent: ShotDirectorIntent,
    assessment: ShotComplexityAssessment,
) -> dict[str, object]:
    """Serialize director intent + complexity into ``Shot.director_state``."""
    return {
        "director_intent": intent.model_dump(mode="json"),
        "complexity_assessment": assessment.model_dump(mode="json"),
    }
