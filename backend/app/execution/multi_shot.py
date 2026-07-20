"""S4 local multi-shot production/review/partial rework with mocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.execution.runtime_invariants import RuntimeState, run_node


@dataclass
class ShotState:
    shot_id: str
    status: str = "pending"
    locked: bool = False
    subtitle: str = ""
    artifact_ids: dict[str, UUID] = field(default_factory=dict)


def produce_shots(n: int = 10) -> list[ShotState]:
    state = RuntimeState(budget_remaining=1000.0)
    shots: list[ShotState] = []
    for i in range(1, n + 1):
        shot = ShotState(shot_id=f"shot-{i:02d}", subtitle=f"Line {i}")
        for node in ("keyframe", "video", "voice", "subtitle", "composite"):
            run = run_node(
                state,
                node_key=f"{shot.shot_id}:{node}",
                input_hash=f"{shot.shot_id}:{node}:v1",
                cost=1.0,
            )
            if run.artifact_id is not None:
                shot.artifact_ids[node] = run.artifact_id
        shot.status = "review_passed"
        shots.append(shot)
    return shots


def rework_subtitle_only(shot: ShotState, new_subtitle: str, state: RuntimeState) -> ShotState:
    """Partial rework: subtitle change invalidates subtitle+composite only."""
    if shot.locked:
        raise ValueError("shot is human-locked")
    shot.subtitle = new_subtitle
    for node in ("subtitle", "composite"):
        run = run_node(
            state,
            node_key=f"{shot.shot_id}:{node}",
            input_hash=f"{shot.shot_id}:{node}:{new_subtitle}",
            cost=1.0,
        )
        if run.artifact_id is not None:
            shot.artifact_ids[node] = run.artifact_id
    # keyframe/video/voice caches preserved (not re-run)
    shot.status = "review_passed"
    return shot
