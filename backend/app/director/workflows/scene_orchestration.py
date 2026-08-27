"""Scene-level production orchestration (WF9).

The Scene is the default production batch boundary: each scene runs its own
planning, graph, budget authorization, review and completion.  Project/Episode
only aggregate state.  This module builds the scene read model and the
prepare/execute status transition; it never builds one giant project graph and
never invents a second queue (it reuses NodeRun single-flight / provider
operations / budget).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.assets.models import Scene, Shot

# Maximum number of scenes that may be in-flight (Producing) at once.
SCENE_CONCURRENCY_LIMIT = 4


class SceneProductionState(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    PRODUCING = "producing"
    REVIEW = "review"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class SceneProductionStatus(BaseModel):
    """Read model for one scene, aggregated from Shot formal artifacts only.

    This is a read aggregation of the existing execution truth (Shot formal
    artifacts / NodeRun), never a second execution truth.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: UUID
    episode_id: UUID
    state: SceneProductionState
    total_shots: int
    formal_shots: int
    failed_shots: int
    review_required: int
    blocked_shots: int
    reasons: list[str] = Field(default_factory=list)

    @property
    def progress(self) -> float:
        if self.total_shots == 0:
            return 0.0
        return round(self.formal_shots / self.total_shots, 3)


def scene_production_status(scene: Scene, shots: list[Shot]) -> SceneProductionStatus:
    """Aggregate one scene's production state from its shots (read only)."""
    total = len(shots)
    formal = sum(1 for shot in shots if shot.formal_video_artifact_id is not None)
    failed = sum(1 for shot in shots if shot.status == "failed")
    review = sum(1 for shot in shots if shot.status == "review")
    blocked = sum(1 for shot in shots if shot.status == "blocked")

    reasons: list[str] = []
    if total == 0:
        state = SceneProductionState.DRAFT
        reasons.append("scene has no shots")
    elif blocked:
        state = SceneProductionState.BLOCKED
        reasons.append(f"{blocked} shot(s) blocked")
    elif failed:
        state = SceneProductionState.REVIEW
        reasons.append(f"{failed} shot(s) failed; review required")
    elif formal == total:
        state = SceneProductionState.COMPLETE
        reasons.append("all shots have formal video")
    elif formal > 0:
        state = SceneProductionState.PRODUCING
        reasons.append("partially produced")
    else:
        state = SceneProductionState.READY
        reasons.append("ready to produce")

    return SceneProductionStatus(
        scene_id=scene.id,
        episode_id=scene.episode_id,
        state=state,
        total_shots=total,
        formal_shots=formal,
        failed_shots=failed,
        review_required=review,
        blocked_shots=blocked,
        reasons=reasons,
    )


def is_scene_failure_isolated(status: SceneProductionStatus) -> bool:
    """A scene only carries its own state; it cannot mark sibling scenes blocked.

    Returns ``True`` for every status that is not a cross-scene failure.  Scenes
    are independent batch boundaries; one scene's failure never contaminates
    another scene's formal artifacts (G-WF-09).
    """
    return status.state is not SceneProductionState.BLOCKED
