"""Work-type-aware production readiness (I8b-01).

One read model answers whether a project can produce its declared work type:
story structure (episodes), scenes/shots, media defaults and formal media. It is
pure read: no Graph, NodeRun or Provider call, and it never fills missing facts.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Episode, Scene, Shot
from app.providers.model_profiles.service import ProductionModelProfileService
from app.shared.errors import NotFoundError


class ReadinessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    status: Literal["ready", "partial", "missing"]
    detail: str


class ProductionReadinessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    work_type: str | None
    planned_episode_count: int | None
    episode_count: int
    scene_count: int
    shot_count: int
    formal_keyframe_count: int
    formal_video_count: int
    formal_composite_count: int
    shared_asset_count: int
    image_binding_configured: bool
    video_binding_configured: bool
    voice_binding_configured: bool
    items: list[ReadinessItem]
    blockers: list[str]
    ready: bool


async def read_production_readiness(
    session: AsyncSession, *, project_id: UUID
) -> ProductionReadinessRead:
    from app.access.models import Project

    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("project not found")
    episode_count = int(
        await session.scalar(
            select(func.count()).select_from(Episode).where(Episode.project_id == project_id)
        )
        or 0
    )
    scene_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Scene)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(Episode.project_id == project_id)
        )
        or 0
    )
    shot_rows = (
        await session.execute(
            select(
                func.count(Shot.id),
                func.count(Shot.formal_keyframe_artifact_id),
                func.count(Shot.formal_video_artifact_id),
                func.count(Shot.formal_composite_artifact_id),
            )
            .select_from(Shot)
            .join(Scene, Scene.id == Shot.scene_id)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(Episode.project_id == project_id)
        )
    ).one()
    shot_count, keyframes, videos, composites = (int(value or 0) for value in shot_rows)
    from app.production.models import ShotReferenceBinding

    shared_subquery = (
        select(ShotReferenceBinding.asset_version_id)
        .join(Shot, Shot.id == ShotReferenceBinding.shot_id)
        .join(Scene, Scene.id == Shot.scene_id)
        .join(Episode, Episode.id == Scene.episode_id)
        .where(Episode.project_id == project_id)
        .where(ShotReferenceBinding.asset_version_id.is_not(None))
        .group_by(ShotReferenceBinding.asset_version_id)
        .having(func.count(func.distinct(Episode.id)) >= 2)
        .subquery()
    )
    shared_assets = int(
        await session.scalar(select(func.count()).select_from(shared_subquery)) or 0
    )
    profile = await ProductionModelProfileService(session).get_effective_for_project(
        project=project
    )
    image_configured = bool(profile is not None and profile.image_model_binding_id)
    video_configured = bool(profile is not None and profile.video_model_binding_id)
    voice_configured = bool(profile is not None and profile.voice_model_binding_id)

    items: list[ReadinessItem] = []
    blockers: list[str] = []

    def add(
        key: str,
        label: str,
        status: Literal["ready", "partial", "missing"],
        detail: str,
        *,
        blocking: bool = True,
    ) -> None:
        items.append(ReadinessItem(key=key, label=label, status=status, detail=detail))
        if blocking and status != "ready":
            blockers.append(key)

    if project.work_type == "single_comic":
        add(
            "story_structure",
            "故事结构",
            "ready" if episode_count == 1 else "missing" if episode_count == 0 else "partial",
            f"单集漫剧需要且只需要1集，当前{episode_count}集",
        )
    elif project.work_type == "serial_comic":
        planned = project.planned_episode_count or 0
        status: Literal["ready", "partial", "missing"] = (
            "ready"
            if episode_count > 0 and (planned == 0 or episode_count >= 2)
            else "missing"
            if episode_count == 0
            else "partial"
        )
        add(
            "story_structure",
            "故事结构",
            status,
            f"多集漫剧计划{planned or '未填'}集，当前{episode_count}集",
        )
    else:
        add(
            "story_structure",
            "故事结构",
            "ready" if episode_count >= 0 else "missing",
            f"{project.work_type or '未声明类型'}，当前{episode_count}集",
            blocking=False,
        )
    add(
        "scenes",
        "场景",
        "ready" if scene_count > 0 else "missing",
        f"当前{scene_count}个场景",
    )
    add(
        "shots",
        "镜头",
        "ready" if shot_count > 0 else "missing",
        f"当前{shot_count}个镜头",
    )
    add(
        "media_defaults",
        "媒体默认",
        "ready"
        if image_configured and video_configured
        else "missing"
        if not (image_configured or video_configured)
        else "partial",
        (
            f"图片{'已配' if image_configured else '未配'}、"
            f"视频{'已配' if video_configured else '未配'}、"
            f"语音{'已配' if voice_configured else '未配'}"
        ),
    )
    add(
        "cross_episode_sharing",
        "跨集共享",
        "ready" if (shared_assets > 0 or episode_count <= 1) else "partial",
        f"{shared_assets}个资产被两集以上引用",
        blocking=False,
    )
    add(
        "formal_media",
        "正式媒体",
        "ready" if keyframes > 0 and videos > 0 else "missing" if keyframes == 0 else "partial",
        f"正式首帧{keyframes}、正式视频{videos}、正式合成{composites}",
        blocking=False,
    )
    return ProductionReadinessRead(
        project_id=project_id,
        work_type=project.work_type,
        planned_episode_count=project.planned_episode_count,
        episode_count=episode_count,
        scene_count=scene_count,
        shot_count=shot_count,
        formal_keyframe_count=keyframes,
        formal_video_count=videos,
        formal_composite_count=composites,
        shared_asset_count=shared_assets,
        image_binding_configured=image_configured,
        video_binding_configured=video_configured,
        voice_binding_configured=voice_configured,
        items=items,
        blockers=blockers,
        ready=not blockers,
    )


__all__ = ["ProductionReadinessRead", "ReadinessItem", "read_production_readiness"]
