"""WF9 — scene-level production orchestration."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from app.assets.models import Scene, Shot
from app.director.workflows.scene_orchestration import (
    SCENE_CONCURRENCY_LIMIT,
    SceneProductionState,
    is_scene_failure_isolated,
    scene_production_status,
)


def _scene() -> Scene:
    return Scene(
        id=uuid4(),
        episode_id=uuid4(),
        scene_number=1,
        location_name="Room",
        time_of_day="night",
        synopsis="",
    )


def _shot(scene_id: UUID, *, status: str, formal: bool = False, n: int = 1) -> Shot:
    return Shot(
        id=uuid4(),
        project_id=uuid4(),
        scene_id=scene_id,
        shot_number=n,
        shot_type="medium",
        camera_move="static",
        visual_description="v",
        dialogue="",
        duration_seconds=Decimal("3"),
        status=status,
        sort_order=n,
        formal_video_artifact_id=uuid4() if formal else None,
    )


def test_scene_status_draft_when_no_shots() -> None:
    scene = _scene()
    status = scene_production_status(scene, [])
    assert status.state == SceneProductionState.DRAFT
    assert status.total_shots == 0


def test_scene_status_ready_when_no_formal() -> None:
    scene = _scene()
    status = scene_production_status(
        scene, [_shot(scene.id, status="draft", n=1), _shot(scene.id, status="draft", n=2)]
    )
    assert status.state == SceneProductionState.READY
    assert status.progress == 0.0


def test_scene_status_complete_when_all_formal() -> None:
    scene = _scene()
    status = scene_production_status(
        scene,
        [
            _shot(scene.id, status="complete", formal=True, n=1),
            _shot(scene.id, status="complete", formal=True, n=2),
        ],
    )
    assert status.state == SceneProductionState.COMPLETE
    assert status.progress == 1.0


def test_scene_status_blocked_and_failure_isolated() -> None:
    scene = _scene()
    status = scene_production_status(
        scene,
        [
            _shot(scene.id, status="blocked", n=1),
            _shot(scene.id, status="complete", formal=True, n=2),
        ],
    )
    assert status.state == SceneProductionState.BLOCKED
    assert status.blocked_shots == 1
    assert is_scene_failure_isolated(status) is False

    # A sibling scene with a healthy status is not contaminated by scene A.
    sibling = _scene()
    sibling_status = scene_production_status(
        sibling, [_shot(sibling.id, status="complete", formal=True)]
    )
    assert sibling_status.state == SceneProductionState.COMPLETE
    assert is_scene_failure_isolated(sibling_status) is True


def test_scene_concurrency_limit_is_bounded() -> None:
    assert SCENE_CONCURRENCY_LIMIT == 4
