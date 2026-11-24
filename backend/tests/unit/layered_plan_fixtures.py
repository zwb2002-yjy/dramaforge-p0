"""Create fresh ORM fixtures for planning/read-model tests, never update facts."""

from uuid import UUID

from app.assets.models import Episode, Scene, Shot
from app.director.workflows.layered_planning import EpisodePlanPayload, SceneStoryboardPlanPayload
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_episode_plan(
    session: AsyncSession, *, project_id: UUID, plan: EpisodePlanPayload,
) -> Episode:
    episode = Episode(project_id=project_id, episode_number=plan.episode_number,
                      title=plan.title[:160], synopsis=plan.story_goal)
    session.add(episode)
    await session.flush()
    session.add_all([
        Scene(episode_id=episode.id, scene_number=scene.scene_number,
              location_name=scene.location[:160], time_of_day=scene.time_of_day[:40],
              synopsis=scene.scene_goal)
        for scene in plan.scenes
    ])
    await session.flush()
    return episode


async def seed_scene_storyboard(
    session: AsyncSession, *, project_id: UUID, scene: Scene,
    storyboard: SceneStoryboardPlanPayload,
) -> list[Shot]:
    shots = [
        Shot(project_id=project_id, scene_id=scene.id, shot_number=shot.shot_number,
             shot_type=shot.shot_type, camera_move=shot.camera_move,
             visual_description=shot.visual_description, dialogue=shot.dialogue,
             duration_seconds=shot.duration_seconds, sort_order=shot.sort_order,
             status="draft", director_state=(
                 {"workflow_template_key": shot.template_key} if shot.template_key else {}
             ))
        for shot in storyboard.shots
    ]
    session.add_all(shots)
    await session.flush()
    return shots
