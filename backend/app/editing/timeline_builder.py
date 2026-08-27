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


async def build_edit_session_for_project(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    name: str = "Long-form Edit",
) -> dict[str, object]:
    """Build an edit session over the full Episode -> Scene -> Shot hierarchy.

    Clips are ordered by ``episode_number``, then ``scene_number``, then
    ``shot.sort_order``.  Every clip carries its ``episode_id`` / ``scene_id`` /
    ``shot_id`` / formal ``artifact_id`` so editing never breaks production
    truth (the formal line is read-only lineage).
    """
    from sqlalchemy import select

    from app.assets.models import Episode, Scene

    episodes = list(
        (
            await session.execute(
                select(Episode)
                .where(Episode.project_id == project_id)
                .order_by(Episode.episode_number)
            )
        ).scalars().all()
    )

    clips: list[dict[str, object]] = []
    lineage: list[dict[str, object]] = []
    for episode in episodes:
        scenes = list(
            (
                await session.execute(
                    select(Scene)
                    .where(Scene.episode_id == episode.id)
                    .order_by(Scene.scene_number)
                )
            ).scalars().all()
        )
        for scene in scenes:
            shots = list(
                (
                    await session.execute(
                        select(Shot)
                        .where(Shot.scene_id == scene.id)
                        .order_by(Shot.sort_order, Shot.shot_number)
                    )
                ).scalars().all()
            )
            for shot in shots:
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
                        "episode_id": str(episode.id),
                        "episode_number": episode.episode_number,
                        "scene_id": str(scene.id),
                        "scene_number": scene.scene_number,
                        "shot_id": str(shot.id),
                        "shot_number": shot.shot_number,
                        "artifact_id": str(shot.formal_video_artifact_id),
                        "duration_seconds": duration,
                        "order": len(clips) + 1,
                        "subtitle": "",
                        "audio_id": None,
                        "transition": None,
                    }
                )
                lineage.append(
                    {
                        "episode_id": str(episode.id),
                        "scene_id": str(scene.id),
                        "shot_id": str(shot.id),
                        "artifact_id": str(shot.formal_video_artifact_id),
                        "order": len(clips),
                    }
                )

    adapter = EditingAdapter(session)
    row = await adapter.create_session(
        project_id=project_id,
        user_id=user_id,
        name=name,
        timeline={
            "clips": clips,
            "metadata": {"auto_built": True, "assembly": "episode_scene_shot"},
        },
        production_lineage={"clips": lineage, "lineage_readonly": True},
    )
    return {
        "session_id": str(row.id),
        "clips": clips,
        "production_lineage": row.production_lineage,
    }
