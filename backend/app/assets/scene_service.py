"""P3-01/P3-03 scene summary and structural commands (reorder/copy/split/merge)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.execution.models import Artifact
from app.shared.errors import NotFoundError, ValidationAppError


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

    async def list_summaries(
        self, *, project_id: UUID, actor: User
    ) -> list[dict[str, object]]:
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
                    func.sum(
                        case((Shot.status == "failed", 1), else_=0)
                    ).label("risk"),
                )
                .where(Shot.scene_id.in_(scene_ids))
                .group_by(Shot.scene_id)
            )
        ).all()
        stats = {
            scene_id: {
                "shot_count": int(shot_count or 0),
                "formal_kf": int(formal_kf or 0),
                "formal_video": int(formal_video or 0),
                "risk": int(risk or 0),
            }
            for scene_id, shot_count, formal_kf, formal_video, risk in stats_rows
        }

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
                await self._session.execute(
                    select(Artifact).where(Artifact.id.in_(artifact_ids))
                )
            ).scalars().all()
            artifacts = {artifact.id: artifact for artifact in artifact_rows}

        summaries: list[dict[str, object]] = []
        for scene, episode_number in scene_rows:
            scene_stats = stats.get(scene.id, {})
            rep_artifact_id = representative.get(scene.id)
            rep_artifact = (
                artifacts.get(rep_artifact_id) if rep_artifact_id is not None else None
            )
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
                    "risk_count": scene_stats.get("risk", 0),
                    "representative_artifact": _artifact_summary(rep_artifact),
                }
            )
        return summaries


class SceneStructureService:
    """Reorder / copy / split / merge with mandatory preview for destructive ops."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _require_scene(
        self, *, project_id: UUID, scene_id: UUID, actor: User
    ) -> Scene:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        scene = (
            await self._session.execute(
                select(Scene)
                .join(Episode, Episode.id == Scene.episode_id)
                .where(Scene.id == scene_id, Episode.project_id == project_id)
            )
        ).scalar_one_or_none()
        if scene is None:
            raise NotFoundError("scene not found")
        return scene

    async def _shots_in_scene(
        self, *, scene_id: UUID
    ) -> list[Shot]:
        rows = (
            await self._session.execute(
                select(Shot)
                .where(Shot.scene_id == scene_id)
                .order_by(Shot.shot_number, Shot.sort_order)
            )
        ).scalars().all()
        return list(rows)

    async def _episode_scene_numbers(
        self, *, episode_id: UUID
    ) -> list[Scene]:
        rows = (
            await self._session.execute(
                select(Scene)
                .where(Scene.episode_id == episode_id)
                .order_by(Scene.scene_number)
            )
        ).scalars().all()
        return list(rows)

    async def reorder(
        self, *, project_id: UUID, scene_id: UUID, actor: User, new_scene_number: int
    ) -> Scene:
        scene = await self._require_scene(project_id=project_id, scene_id=scene_id, actor=actor)
        if new_scene_number < 1:
            raise ValidationAppError("scene_number must be >= 1")
        siblings = await self._episode_scene_numbers(episode_id=scene.episode_id)
        numbers = [item.scene_number for item in siblings if item.id != scene.id]
        if new_scene_number in numbers:
            raise ValidationAppError("scene_number already in use")
        scene.scene_number = new_scene_number
        await self._session.flush()
        return scene

    async def copy(
        self, *, project_id: UUID, scene_id: UUID, actor: User
    ) -> Scene:
        scene = await self._require_scene(project_id=project_id, scene_id=scene_id, actor=actor)
        siblings = await self._episode_scene_numbers(episode_id=scene.episode_id)
        max_number = max((item.scene_number for item in siblings), default=0)
        new_scene = Scene(
            episode_id=scene.episode_id,
            scene_number=max_number + 1,
            location_name=f"{scene.location_name}（副本）",
            time_of_day=scene.time_of_day,
            synopsis=scene.synopsis,
            design_state=dict(scene.design_state or {}),
        )
        self._session.add(new_scene)
        await self._session.flush()
        for shot in await self._shots_in_scene(scene_id=scene.id):
            self._session.add(
                Shot(
                    project_id=project_id,
                    scene_id=new_scene.id,
                    shot_number=shot.shot_number,
                    shot_type=shot.shot_type,
                    camera_move=shot.camera_move,
                    visual_description=shot.visual_description,
                    dialogue=shot.dialogue,
                    duration_seconds=shot.duration_seconds,
                    status="draft",
                    sort_order=shot.sort_order,
                    director_state=dict(shot.director_state or {}),
                    image_prompt=shot.image_prompt,
                    video_prompt=shot.video_prompt,
                )
            )
        await self._session.flush()
        return new_scene

    async def _affected_report(
        self, *, scene_id: UUID, project_id: UUID
    ) -> dict[str, object]:
        from app.production.models import ExperimentBranch

        shots = await self._shots_in_scene(scene_id=scene_id)
        shot_ids = [shot.id for shot in shots]
        experiments = []
        formal_media: list[dict[str, object]] = []
        if shot_ids:
            exp_rows = (
                await self._session.execute(
                    select(ExperimentBranch.id, ExperimentBranch.source_shot_id)
                    .where(ExperimentBranch.project_id == project_id)
                    .where(ExperimentBranch.source_shot_id.in_(shot_ids))
                )
            ).all()
            experiments = [
                {"id": exp_id, "source_shot_id": source_shot_id}
                for exp_id, source_shot_id in exp_rows
            ]
            for shot in shots:
                for field, label in (
                    ("formal_keyframe_artifact_id", "keyframe"),
                    ("formal_video_artifact_id", "video"),
                    ("formal_composite_artifact_id", "composite"),
                ):
                    artifact_id = getattr(shot, field)
                    if artifact_id is not None:
                        formal_media.append(
                            {
                                "shot_id": shot.id,
                                "kind": label,
                                "artifact_id": artifact_id,
                            }
                        )
        return {
            "shot_ids": shot_ids,
            "shot_count": len(shots),
            "experiment_ids": [item["id"] for item in experiments],
            "experiment_count": len(experiments),
            "formal_media": formal_media,
            "formal_media_count": len(formal_media),
        }

    async def split_preview(
        self, *, project_id: UUID, scene_id: UUID, actor: User, at_shot_number: int
    ) -> dict[str, object]:
        scene = await self._require_scene(project_id=project_id, scene_id=scene_id, actor=actor)
        shots = await self._shots_in_scene(scene_id=scene.id)
        if at_shot_number <= min((s.shot_number for s in shots), default=0) or at_shot_number > max(
            (s.shot_number for s in shots), default=1
        ):
            raise ValidationAppError("at_shot_number must split between shots")
        moving = [shot.id for shot in shots if shot.shot_number >= at_shot_number]
        if not moving:
            raise ValidationAppError("no shots to move")
        report = await self._affected_report(scene_id=scene.id, project_id=project_id)
        return {
            "scene_id": scene.id,
            "at_shot_number": at_shot_number,
            "new_scene_hint": f"{scene.location_name}（续）",
            "affected": {**report, "shot_ids": moving, "shot_count": len(moving)},
        }

    async def split(
        self,
        *,
        project_id: UUID,
        scene_id: UUID,
        actor: User,
        at_shot_number: int,
        title: str | None = None,
        location_name: str | None = None,
        time_of_day: str | None = None,
    ) -> Scene:
        scene = await self._require_scene(project_id=project_id, scene_id=scene_id, actor=actor)
        shots = await self._shots_in_scene(scene_id=scene.id)
        if at_shot_number <= min((s.shot_number for s in shots), default=0):
            raise ValidationAppError("at_shot_number must split between shots")
        moving = [shot for shot in shots if shot.shot_number >= at_shot_number]
        if not moving:
            raise ValidationAppError("no shots to move")
        siblings = await self._episode_scene_numbers(episode_id=scene.episode_id)
        new_number = scene.scene_number + 1
        for sibling in siblings:
            if sibling.id != scene.id and sibling.scene_number >= new_number:
                sibling.scene_number += 1
        new_scene = Scene(
            episode_id=scene.episode_id,
            scene_number=new_number,
            location_name=location_name or f"{scene.location_name}（续）",
            time_of_day=time_of_day or scene.time_of_day,
            synopsis=scene.synopsis,
            design_state={},
        )
        self._session.add(new_scene)
        await self._session.flush()
        for shot in moving:
            shot.scene_id = new_scene.id
            shot.sort_order = shot.shot_number
        await self._session.flush()
        return new_scene

    async def merge_preview(
        self, *, project_id: UUID, scene_id: UUID, target_scene_id: UUID, actor: User
    ) -> dict[str, object]:
        scene = await self._require_scene(project_id=project_id, scene_id=scene_id, actor=actor)
        target = await self._require_scene(
            project_id=project_id, scene_id=target_scene_id, actor=actor
        )
        if scene.episode_id != target.episode_id:
            raise ValidationAppError("cannot merge scenes from different episodes")
        report = await self._affected_report(scene_id=target.id, project_id=project_id)
        return {
            "scene_id": scene.id,
            "target_scene_id": target.id,
            "kept_scene_name": scene.location_name,
            "absorbed_scene_name": target.location_name,
            "affected": report,
        }

    async def merge(
        self, *, project_id: UUID, scene_id: UUID, target_scene_id: UUID, actor: User
    ) -> Scene:
        scene = await self._require_scene(project_id=project_id, scene_id=scene_id, actor=actor)
        target = await self._require_scene(
            project_id=project_id, scene_id=target_scene_id, actor=actor
        )
        if scene.episode_id != target.episode_id:
            raise ValidationAppError("cannot merge scenes from different episodes")
        if scene.id == target.id:
            raise ValidationAppError("cannot merge a scene into itself")
        target_shots = await self._shots_in_scene(scene_id=target.id)
        max_number = max(
            (shot.shot_number for shot in await self._shots_in_scene(scene_id=scene.id)),
            default=0,
        )
        for offset, shot in enumerate(target_shots, start=1):
            shot.scene_id = scene.id
            shot.shot_number = max_number + offset
            shot.sort_order = max_number + offset
        await self._session.delete(target)
        # Renumber remaining scenes after the absorbed one.
        siblings = await self._episode_scene_numbers(episode_id=scene.episode_id)
        expected = 1
        for sibling in siblings:
            if sibling.id == scene.id:
                continue
            if sibling.scene_number != expected:
                sibling.scene_number = expected
            expected += 1
        await self._session.flush()
        return scene
