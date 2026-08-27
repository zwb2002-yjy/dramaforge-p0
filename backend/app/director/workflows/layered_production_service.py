"""Layered production materialization service (WF8).

Converts an EpisodePlanPayload / SceneStoryboardPlanPayload into real
Episode / Scene / Shot rows, idempotently (stable number-keyed lookup, no
duplicate materialization).  Materialization is separate from execution: this
service never enqueues a paid Provider call.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Episode, Scene, Shot
from app.director.workflows.layered_planning import (
    EpisodePlanPayload,
    SceneStoryboardPlanPayload,
)
from app.shared.errors import ValidationAppError


async def materialize_episode_plan(
    session: AsyncSession,
    *,
    project_id: UUID,
    plan: EpisodePlanPayload,
) -> Episode:
    """Create/update the Episode and its Scenes from an episode plan."""
    episode = await session.scalar(
        select(Episode).where(
            Episode.project_id == project_id,
            Episode.episode_number == plan.episode_number,
        )
    )
    if episode is None:
        episode = Episode(
            project_id=project_id,
            episode_number=plan.episode_number,
            title=plan.title[:160],
            synopsis=plan.story_goal,
        )
        session.add(episode)
        await session.flush()
    else:
        episode.title = plan.title[:160]
        episode.synopsis = plan.story_goal

    # Materialize scenes idempotently by scene_number.
    for scene_plan in plan.scenes:
        scene = await session.scalar(
            select(Scene).where(
                Scene.episode_id == episode.id,
                Scene.scene_number == scene_plan.scene_number,
            )
        )
        if scene is None:
            scene = Scene(
                episode_id=episode.id,
                scene_number=scene_plan.scene_number,
                location_name=scene_plan.location[:160],
                time_of_day=scene_plan.time_of_day[:40],
                synopsis=scene_plan.scene_goal,
            )
            session.add(scene)
            await session.flush()
        else:
            scene.location_name = scene_plan.location[:160]
            scene.time_of_day = scene_plan.time_of_day[:40]
            scene.synopsis = scene_plan.scene_goal
    await session.flush()
    return episode


async def materialize_scene_storyboard(
    session: AsyncSession,
    *,
    project_id: UUID,
    scene: Scene,
    storyboard: SceneStoryboardPlanPayload,
) -> list[Shot]:
    """Create/update the Shots for one scene from a storyboard plan."""
    created: list[Shot] = []
    for shot_plan in storyboard.shots:
        shot = await session.scalar(
            select(Shot).where(
                Shot.scene_id == scene.id,
                Shot.shot_number == shot_plan.shot_number,
            )
        )
        if shot is None:
            shot = Shot(
                project_id=project_id,
                scene_id=scene.id,
                shot_number=shot_plan.shot_number,
                shot_type=shot_plan.shot_type,
                camera_move=shot_plan.camera_move,
                visual_description=shot_plan.visual_description,
                dialogue=shot_plan.dialogue,
                duration_seconds=shot_plan.duration_seconds,
                sort_order=shot_plan.sort_order,
                status="draft",
            )
            session.add(shot)
            await session.flush()
        else:
            shot.shot_type = shot_plan.shot_type
            shot.camera_move = shot_plan.camera_move
            shot.visual_description = shot_plan.visual_description
            shot.dialogue = shot_plan.dialogue
            shot.duration_seconds = Decimal(str(shot_plan.duration_seconds))
            shot.sort_order = shot_plan.sort_order
        if shot_plan.template_key:
            # Freeze the workflow template identity on the shot (G-WF-03).
            shot.director_state = {
                **(shot.director_state or {}),
                "workflow_template_key": shot_plan.template_key,
            }
        created.append(shot)
    await session.flush()
    return created


async def require_episode_scene(
    session: AsyncSession,
    *,
    project_id: UUID,
    episode_id: UUID,
    scene_number: int,
) -> Scene:
    """Resolve a scene within an episode, failing closed on cross-project."""
    episode = await session.get(Episode, episode_id)
    if episode is None or episode.project_id != project_id:
        raise ValidationAppError("episode not found in project")
    scene = await session.scalar(
        select(Scene).where(
            Scene.episode_id == episode_id,
            Scene.scene_number == scene_number,
        )
    )
    if scene is None:
        raise ValidationAppError("scene not found in episode")
    return scene
