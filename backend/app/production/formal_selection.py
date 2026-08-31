"""P4-08 Keyframe formal selection (03 §38).

Formal selection picks a concrete keyframe *artifact* from a keyframe NodeRun of
the shot (candidates come from NodeRun + Artifact, no Candidate table).

Video execution (P4-09) defaults to the formal keyframe and MUST NOT fall back
to "the latest image" when no formal keyframe exists: :func:`require_formal_keyframe`
fails closed instead.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Shot
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.models import GraphVersion, ProductionGraph
from app.shared.errors import ValidationAppError

_NO_FORMAL_KEYFRAME = (
    "shot has no formal keyframe; video execution requires a formal keyframe "
    "and must not fall back to the latest image"
)

# ``NodeRun`` is the durable execution status.  Cached output and a completed
# run that observed cancellation are still successful immutable outputs.  The
# legacy ``succeeded`` spelling is retained for historical/manual fixtures;
# production Worker runs use the enum values above.
_SUCCESSFUL_RUN_STATUSES = {
    "completed",
    "cached",
    "completed_after_cancel",
    "succeeded",
}
_AVAILABLE_ARTIFACT_STATES = {"available", "stored"}


class _ShotVersionConflict(ValidationAppError):
    """A formal-selection version conflict exposed as HTTP 409.

    The historical unit contract catches ``ValidationAppError`` for this
    service, so keep that inheritance while returning the correct conflict
    status at the API boundary.
    """

    def __init__(self, message: str = "shot changed concurrently") -> None:
        super().__init__(
            message,
            details={"code": "SHOT_VERSION_MISMATCH"},
        )
        self.code = "CONFLICT"
        self.status_code = 409


async def _candidate_lineage(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
    expected_stage: str,
    expected_artifact_type: str,
) -> tuple[Artifact, NodeRun, GraphNode] | None:
    """Return the verified NodeRun lineage for one formal candidate.

    The graph scope is the authoritative shot boundary.  The optional
    ``input_snapshot`` checks strengthen the boundary for newer Workbench
    runs while retaining read compatibility with historical runs that only
    recorded the graph node.  ``produced_by_run_id`` is the Artifact-side
    lineage; when a run has a result pointer it must agree with it as well.
    """
    row = (
        await session.execute(
            select(Artifact, NodeRun, GraphNode)
            .join(NodeRun, NodeRun.id == Artifact.produced_by_run_id)
            .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
            .join(GraphVersion, GraphVersion.id == GraphNode.graph_version_id)
            .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
            .where(
                Artifact.id == artifact_id,
                Artifact.project_id == project_id,
                NodeRun.project_id == project_id,
                ProductionGraph.project_id == project_id,
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id == shot_id,
                NodeRun.graph_version_id == GraphNode.graph_version_id,
                GraphNode.node_type == expected_stage,
            )
        )
    ).first()
    if row is None:
        return None

    artifact, run, node = row
    if run.status not in _SUCCESSFUL_RUN_STATUSES:
        return None
    if artifact.artifact_type != expected_artifact_type:
        return None
    if artifact.storage_state not in _AVAILABLE_ARTIFACT_STATES:
        return None
    if artifact.deleted_at is not None:
        return None
    if run.result_artifact_id is not None and run.result_artifact_id != artifact.id:
        return None

    snapshot = dict(run.input_snapshot or {})
    snapshot_shot_id = snapshot.get("shot_id")
    if snapshot_shot_id is not None and str(snapshot_shot_id) != str(shot_id):
        return None
    snapshot_stage = snapshot.get("stage")
    expected_snapshot_stage = "image_keyframe" if expected_stage == "keyframe" else "video"
    if snapshot_stage is not None and str(snapshot_stage) != expected_snapshot_stage:
        return None
    snapshot_node_key = snapshot.get("node_key")
    if snapshot_node_key is not None and str(snapshot_node_key) != node.node_key:
        return None
    return artifact, run, node


async def list_formal_candidates(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_ids: list[UUID],
) -> dict[UUID, list[dict[str, object]]]:
    """List successful image/video artifacts for the supplied shot scope.

    This is a read-side projection of the existing ``NodeRun`` + ``Artifact``
    lineage.  It deliberately does not introduce a Candidate table or a
    second formal-output truth.  Experiment branch rows can still be returned
    by the scene workspace alongside these concrete artifacts.
    """
    result: dict[UUID, list[dict[str, object]]] = {shot_id: [] for shot_id in shot_ids}
    if not shot_ids:
        return result

    rows = (
        await session.execute(
            select(Artifact, NodeRun, GraphNode, ProductionGraph)
            .join(NodeRun, NodeRun.id == Artifact.produced_by_run_id)
            .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
            .join(GraphVersion, GraphVersion.id == GraphNode.graph_version_id)
            .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
            .where(
                Artifact.project_id == project_id,
                NodeRun.project_id == project_id,
                ProductionGraph.project_id == project_id,
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id.in_(shot_ids),
                NodeRun.graph_version_id == GraphNode.graph_version_id,
                GraphNode.node_type.in_(("keyframe", "video")),
                Artifact.artifact_type.in_(("image", "video")),
            )
            .order_by(Artifact.created_at.desc())
        )
    ).all()
    for artifact, run, node, graph in rows:
        if run.status not in _SUCCESSFUL_RUN_STATUSES:
            continue
        expected_stage = "keyframe" if node.node_type == "keyframe" else "video"
        expected_type = "image" if expected_stage == "keyframe" else "video"
        if artifact.artifact_type != expected_type:
            continue
        if artifact.storage_state not in _AVAILABLE_ARTIFACT_STATES:
            continue
        if artifact.deleted_at is not None:
            continue
        if run.result_artifact_id is not None and run.result_artifact_id != artifact.id:
            continue
        snapshot = dict(run.input_snapshot or {})
        snapshot_shot_id = snapshot.get("shot_id")
        if snapshot_shot_id is not None and str(snapshot_shot_id) != str(graph.scope_entity_id):
            continue
        snapshot_stage = snapshot.get("stage")
        if snapshot_stage is not None and str(snapshot_stage) != (
            "image_keyframe" if expected_stage == "keyframe" else "video"
        ):
            continue
        snapshot_node_key = snapshot.get("node_key")
        if snapshot_node_key is not None and str(snapshot_node_key) != node.node_key:
            continue
        result.setdefault(graph.scope_entity_id, []).append(
            {
                # ``id`` keeps the envelope convenient for existing opaque
                # candidate consumers; ``artifact_id`` is the explicit
                # command payload source used by the formal action.
                "id": artifact.id,
                "artifact_id": artifact.id,
                "node_run_id": run.id,
                "node_key": node.node_key,
                "stage": "image_keyframe" if expected_stage == "keyframe" else "video",
                "status": run.status,
                "artifact_type": artifact.artifact_type,
                "mime_type": artifact.mime_type,
                "content_hash": artifact.content_hash,
                "byte_size": artifact.byte_size,
                "storage_state": artifact.storage_state,
                "created_at": artifact.created_at,
            }
        )
    return result


async def _is_keyframe_candidate(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
) -> bool:
    """True when the artifact is produced by a keyframe NodeRun of this shot."""
    return (
        await _candidate_lineage(
            session,
            project_id=project_id,
            shot_id=shot_id,
            artifact_id=artifact_id,
            expected_stage="keyframe",
            expected_artifact_type="image",
        )
    ) is not None


async def set_formal_keyframe(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
    expected_shot_version: int | None = None,
) -> Shot:
    """Validate and set ``Shot.formal_keyframe_artifact_id`` (03 §38)."""
    shot = await session.scalar(
        select(Shot)
        .where(Shot.id == shot_id, Shot.project_id == project_id)
        .with_for_update()
    )
    if shot is None:
        raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
    if expected_shot_version is not None and (shot.version or 1) != expected_shot_version:
        raise _ShotVersionConflict()

    artifact = await session.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise ValidationAppError(
            "artifact not found in project",
            details={"code": "ARTIFACT_NOT_FOUND"},
        )
    if not await _is_keyframe_candidate(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=artifact_id,
    ):
        raise ValidationAppError(
            "artifact is not a keyframe result of this shot",
            details={"code": "NOT_KEYFRAME_CANDIDATE"},
        )
    shot.formal_keyframe_artifact_id = artifact_id
    shot.version = (shot.version or 1) + 1
    return shot


async def require_formal_keyframe(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
) -> Artifact:
    """Return the formal keyframe artifact or fail closed (no latest-image
    fallback for video execution)."""
    shot = await session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
    if shot.formal_keyframe_artifact_id is None:
        raise ValidationAppError(
            _NO_FORMAL_KEYFRAME,
            details={"code": "NO_FORMAL_KEYFRAME"},
        )
    artifact = await session.get(Artifact, shot.formal_keyframe_artifact_id)
    if (
        artifact is None
        or artifact.project_id != project_id
        or artifact.artifact_type != "image"
        or artifact.storage_state not in _AVAILABLE_ARTIFACT_STATES
        or artifact.deleted_at is not None
    ):
        raise ValidationAppError(
            _NO_FORMAL_KEYFRAME,
            details={"code": "NO_FORMAL_KEYFRAME"},
        )
    return artifact


async def set_formal_video(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
    expected_shot_version: int | None = None,
) -> Shot:
    """Validate and set ``Shot.formal_video_artifact_id`` (03 §39)."""
    shot = await session.scalar(
        select(Shot)
        .where(Shot.id == shot_id, Shot.project_id == project_id)
        .with_for_update()
    )
    if shot is None:
        raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
    if expected_shot_version is not None and (shot.version or 1) != expected_shot_version:
        raise _ShotVersionConflict()

    artifact = await session.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise ValidationAppError(
            "artifact not found in project",
            details={"code": "ARTIFACT_NOT_FOUND"},
        )
    lineage = await _candidate_lineage(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=artifact_id,
        expected_stage="video",
        expected_artifact_type="video",
    )
    if lineage is None:
        raise ValidationAppError(
            "artifact is not a video result of this shot",
            details={"code": "NOT_VIDEO_CANDIDATE"},
        )
    shot.formal_video_artifact_id = artifact_id
    shot.version = (shot.version or 1) + 1
    return shot
