"""Phase 9 Production -> Edit Timeline builder (03 §83)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Shot
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact


async def build_edit_session_from_shots(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    shot_ids: list[UUID],
    name: str = "Production Edit",
) -> dict[str, object]:
    """Create an edit session from formal shot videos (03 §83).

    Inputs per shot: formal video artifact, shot order, duration. Lineage is
    recorded read-only; the formal line is never mutated.
    """
    clips: list[dict[str, object]] = []
    lineage_shots: list[dict[str, object]] = []
    for order, shot_id in enumerate(shot_ids, start=1):
        shot = await session.get(Shot, shot_id)
        if shot is None or shot.project_id != project_id:
            continue
        if shot.formal_video_artifact_id is None:
            continue
        artifact = await session.get(Artifact, shot.formal_video_artifact_id)
        duration = (
            float(artifact.duration_seconds)
            if artifact and artifact.duration_seconds
            else 0.0
        )
        clips.append(
            {
                "id": str(uuid4()),
                "shot_id": str(shot.id),
                "artifact_id": str(shot.formal_video_artifact_id),
                "order": order,
                "duration_seconds": duration,
                "subtitle": "",
                "audio_id": None,
                "transition": None,
            }
        )
        lineage_shots.append({"shot_id": str(shot.id), "order": order})

    adapter = EditingAdapter(session)
    row = await adapter.create_session(
        project_id=project_id,
        user_id=user_id,
        name=name,
        timeline={"clips": clips, "metadata": {"auto_built": True}},
        production_lineage={"shots": lineage_shots, "lineage_readonly": True},
    )
    return {
        "session_id": str(row.id),
        "clips": clips,
        "production_lineage": row.production_lineage,
    }
