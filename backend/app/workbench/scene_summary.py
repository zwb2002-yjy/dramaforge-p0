"""Project storyboard aggregation over domain and production facts; batch reads only."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.execution.models import Artifact
from app.production.shot_overview import load_shot_overview


def _artifact_summary(artifact: Artifact | None) -> dict[str, object] | None:
    if artifact is None:
        return None
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "mime_type": artifact.mime_type,
        "content_hash": artifact.content_hash,
        "byte_size": artifact.byte_size,
        "storage_state": artifact.storage_state,
    }


class SceneSummaryService:
    """Batch scene summary aggregation (no per-scene N+1 NodeRun queries)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_summaries(self, *, project_id: UUID, actor: User) -> list[dict[str, object]]:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        scene_rows = (
            await self._session.execute(
                select(Scene, Episode.episode_number)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Episode.project_id == project_id)
                .order_by(Episode.episode_number, Scene.scene_number)
            )
        ).all()
        scene_ids = [scene.id for scene, _ in scene_rows]
        if not scene_ids:
            return []

        stats_rows = (
            await self._session.execute(
                select(
                    Shot.scene_id,
                    func.count().label("shot_count"),
                    func.sum(
                        case(
                            (Shot.formal_keyframe_artifact_id.is_not(None), 1),
                            else_=0,
                        )
                    ).label("formal_kf"),
                    func.sum(
                        case(
                            (Shot.formal_video_artifact_id.is_not(None), 1),
                            else_=0,
                        )
                    ).label("formal_video"),
                )
                .where(Shot.project_id == project_id, Shot.scene_id.in_(scene_ids))
                .group_by(Shot.scene_id)
            )
        ).all()
        stats = {
            scene_id: {
                "shot_count": int(shot_count or 0),
                "formal_kf": int(formal_kf or 0),
                "formal_video": int(formal_video or 0),
            }
            for scene_id, shot_count, formal_kf, formal_video in stats_rows
        }
        shots = list(
            (
                await self._session.scalars(
                    select(Shot).where(Shot.project_id == project_id, Shot.scene_id.in_(scene_ids))
                )
            ).all()
        )
        overview = await load_shot_overview(self._session, project_id=project_id, shots=shots)
        scene_overview: dict[UUID, dict[str, int]] = {}
        for shot in shots:
            counts = scene_overview.setdefault(
                shot.scene_id,
                {
                    "pending_review_count": 0,
                    "generating_count": 0,
                    "failed_count": 0,
                    "unknown_count": 0,
                    "risk_count": 0,
                },
            )
            facts = overview[shot.id]
            counts["pending_review_count"] += int(facts["pending_review"])
            counts["generating_count"] += int(facts["generating"])
            counts["failed_count"] += int(facts["generation_failed"])
            counts["unknown_count"] += int(facts["outcome_unknown"])
            counts["risk_count"] += int(facts["generation_failed"] or facts["outcome_unknown"])

        rep_rows = (
            await self._session.execute(
                select(Shot.scene_id, Shot.formal_keyframe_artifact_id)
                .where(
                    Shot.scene_id.in_(scene_ids),
                    Shot.formal_keyframe_artifact_id.is_not(None),
                )
                .order_by(Shot.scene_id, Shot.shot_number)
            )
        ).all()
        representative: dict[UUID, UUID] = {}
        for scene_id, artifact_id in rep_rows:
            representative.setdefault(scene_id, artifact_id)
        artifact_ids = set(representative.values())
        artifacts: dict[UUID, Artifact] = {}
        if artifact_ids:
            artifact_rows = (
                (await self._session.execute(select(Artifact).where(Artifact.id.in_(artifact_ids))))
                .scalars()
                .all()
            )
            artifacts = {artifact.id: artifact for artifact in artifact_rows}

        summaries: list[dict[str, object]] = []
        for scene, episode_number in scene_rows:
            scene_stats = stats.get(scene.id, {})
            rep_artifact_id = representative.get(scene.id)
            rep_artifact = artifacts.get(rep_artifact_id) if rep_artifact_id is not None else None
            summaries.append(
                {
                    "id": scene.id,
                    "episode_id": scene.episode_id,
                    "episode_number": episode_number,
                    "scene_number": scene.scene_number,
                    "location_name": scene.location_name,
                    "time_of_day": scene.time_of_day,
                    "synopsis": scene.synopsis,
                    "version": scene.version,
                    "shot_count": scene_stats.get("shot_count", 0),
                    "formal_keyframe_count": scene_stats.get("formal_kf", 0),
                    "formal_video_count": scene_stats.get("formal_video", 0),
                    **scene_overview.get(
                        scene.id,
                        {
                            "pending_review_count": 0,
                            "generating_count": 0,
                            "failed_count": 0,
                            "unknown_count": 0,
                            "risk_count": 0,
                        },
                    ),
                    "representative_artifact": _artifact_summary(rep_artifact),
                }
            )
        return summaries
