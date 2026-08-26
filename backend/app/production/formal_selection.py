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


async def _is_keyframe_candidate(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
) -> bool:
    """True when the artifact is produced by a keyframe NodeRun of this shot."""
    row = (
        await session.execute(
            select(Artifact.id)
            .join(NodeRun, NodeRun.id == Artifact.produced_by_run_id)
            .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
            .join(GraphVersion, GraphVersion.id == GraphNode.graph_version_id)
            .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
            .where(
                Artifact.id == artifact_id,
                Artifact.project_id == project_id,
                GraphNode.node_type == "keyframe",
                ProductionGraph.scope_type == "shot",
                ProductionGraph.scope_entity_id == shot_id,
            )
        )
    ).first()
    return row is not None


async def set_formal_keyframe(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    artifact_id: UUID,
    expected_shot_version: int | None = None,
) -> Shot:
    """Validate and set ``Shot.formal_keyframe_artifact_id`` (03 §38)."""
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
    shot = await session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
    if expected_shot_version is not None and (shot.version or 1) != expected_shot_version:
        raise ValidationAppError(
            "shot changed concurrently",
            details={"code": "SHOT_VERSION_MISMATCH"},
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
    if artifact is None or artifact.project_id != project_id:
        raise ValidationAppError(
            _NO_FORMAL_KEYFRAME,
            details={"code": "NO_FORMAL_KEYFRAME"},
        )
    return artifact
