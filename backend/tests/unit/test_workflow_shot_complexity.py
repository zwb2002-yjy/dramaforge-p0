"""WF7 — complex shot intent / risk assessment."""

from __future__ import annotations

from uuid import uuid4

from app.director.workflows.character_participation import (
    ScreenRole,
    ShotCharacterParticipation,
    ShotParticipationPlan,
)
from app.director.workflows.shot_complexity import (
    CameraMotion,
    ComplexityStrategy,
    ShotDirectorIntent,
    assess_shot_complexity,
    complexity_director_state,
)


def _plan(n: int, *, visible: bool = True) -> ShotParticipationPlan:
    return ShotParticipationPlan(
        participations=[
            ShotCharacterParticipation(
                character_id=uuid4(),
                asset_version_id=uuid4() if visible else None,
                screen_role=(
                    ScreenRole.PRIMARY
                    if i == 0
                    else (ScreenRole.SECONDARY if visible else ScreenRole.OFFSCREEN)
                ),
            )
            for i in range(n)
        ]
    )


def test_single_character_static_is_single_pass() -> None:
    assessment = assess_shot_complexity(
        intent=ShotDirectorIntent(camera_motion=CameraMotion.STATIC),
        participation_plan=_plan(1),
    )
    assert assessment.strategy == ComplexityStrategy.SINGLE_PASS


def test_two_character_with_tracking_requires_staged() -> None:
    assessment = assess_shot_complexity(
        intent=ShotDirectorIntent(camera_motion=CameraMotion.TRACKING),
        participation_plan=_plan(2),
    )
    assert assessment.strategy == ComplexityStrategy.STAGED
    assert assessment.camera_complexity.value == "high"
    assert assessment.character_count == 2


def test_three_character_with_interaction_needs_experiment() -> None:
    assessment = assess_shot_complexity(
        intent=ShotDirectorIntent(
            subject_blocking=["A and B embrace"],
            subject_motion=["crossing"],
        ),
        participation_plan=_plan(3),
    )
    assert assessment.strategy == ComplexityStrategy.NEEDS_EXPERIMENT
    assert assessment.interaction_complexity.value == "high"


def test_four_character_without_interaction_needs_experiment() -> None:
    # Four is the platform safety limit; with no interaction/motion it is a
    # needs-experiment (identity risk) shot, never an automatic single pass.
    assessment = assess_shot_complexity(
        intent=ShotDirectorIntent(),
        participation_plan=_plan(4),
    )
    assert assessment.strategy == ComplexityStrategy.NEEDS_EXPERIMENT
    assert assessment.identity_risk.value == "high"


def test_director_state_serialization() -> None:
    intent = ShotDirectorIntent(camera_motion=CameraMotion.PAN)
    assessment = assess_shot_complexity(intent=intent, participation_plan=_plan(1))
    state = complexity_director_state(intent, assessment)
    assert state["director_intent"]["camera_motion"] == "pan"
    assert state["complexity_assessment"]["strategy"] == "SINGLE_PASS"
