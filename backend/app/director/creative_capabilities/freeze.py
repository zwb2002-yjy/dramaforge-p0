"""Creative capability freeze (CC10) — write frozen provenance onto existing state.

The compiled creative intent's provenance is frozen onto the current fact stores
(``Scene.design_state`` / ``Shot.director_state``) — never a second truth, never
a new graph.  The freeze is a *user-explicit* selection only; it never auto-applies
a style/skill without preview (G-CC-02/03).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Episode, Scene, Shot
from app.director.creative_capabilities.creative_compiler import CompiledCreativeIntent
from app.shared.errors import ValidationAppError


def __serialize_provenance(intent: CompiledCreativeIntent) -> dict[str, object]:
    return dict(intent.provenance)


async def _scene_in_project(session: AsyncSession, scene_id: UUID, project_id: UUID) -> Scene:
    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise ValidationAppError("scene not found", details={"code": "SCENE_NOT_FOUND"})
    episode = await session.get(Episode, scene.episode_id)
    if episode is None or episode.project_id != project_id:
        raise ValidationAppError("scene not found", details={"code": "SCENE_NOT_FOUND"})
    return scene


async def freeze_scene_capabilities(
    session: AsyncSession,
    *,
    project_id: UUID,
    scene_id: UUID,
    intent: CompiledCreativeIntent,
    actor_id: UUID,
) -> Scene:
    """Freeze the compiled creative provenance onto a Scene's design_state."""
    scene = await _scene_in_project(session, scene_id, project_id)
    design = dict(scene.design_state or {})
    design["creative_capabilities"] = __serialize_provenance(intent)
    scene.design_state = design
    scene.version = (scene.version or 1) + 1
    await session.flush()
    return scene


async def freeze_shot_capabilities(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    intent: CompiledCreativeIntent,
    actor_id: UUID,
) -> Shot:
    """Freeze the compiled creative provenance onto a Shot's director_state."""
    shot = await session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
    state = dict(shot.director_state or {})
    state["creative_capabilities"] = __serialize_provenance(intent)
    shot.director_state = state
    shot.version = (shot.version or 1) + 1
    await session.flush()
    return shot
