"""Read recorded creative selections and adopted scope snapshots without recompiling.

The caller owns actor/workspace authorization. This reader rechecks the complete
project/episode/scene/shot chain, performs no writes, and does not consult pending
proposals or the current pack library. Separate sources retain their own versions
and value provenance; recorded defaults never become accepted-proposal values.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, ProjectCreativeProfile
from app.assets.models import Episode, Scene, Shot
from app.shared.errors import NotFoundError, ValidationAppError


def _invalid(message: str) -> ValidationAppError:
    return ValidationAppError(message, details={"code": "DIRECTOR_CREATIVE_CONTEXT_INVALID"})


def _json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise _invalid("Recorded creative context must contain finite JSON values") from exc


def _source(
    source_type: str,
    source_id: UUID,
    source_version: int,
    state: object,
) -> dict[str, object]:
    if not isinstance(state, dict):
        raise _invalid("Recorded creative design state must be an object")
    frozen = state.get("creative_capabilities")
    if frozen is not None and not isinstance(frozen, dict):
        raise _invalid("Recorded creative capability snapshot must be an object")
    return {
        "source_type": source_type,
        "source_id": str(source_id),
        "source_version": source_version,
        "available": bool(frozen),
        "creative_capabilities": frozen if frozen else None,
        "interpretation": "recorded_snapshot_not_recompiled",
    }


async def load_agent_creative_context(
    session: AsyncSession,
    *,
    project_id: UUID,
    scope_type: Literal["project", "story", "scene", "shot"],
    scope_entity_id: UUID,
    max_bytes: int = 24_000,
) -> dict[str, object]:
    """Return detached selected IDs and separate persisted Scene/Shot snapshots.

    ``available`` reports that a saved snapshot exists; it is not a fresh quality
    certification or a recomputation of its recorded hash. Missing snapshots stay
    unavailable. ``strategy_snapshot`` is deliberately excluded: initialization
    strategies do not establish current adopted creative choices.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= 65_536:
        raise _invalid("Creative context byte limit must be between 1 and 65536")
    if scope_type not in {"project", "story", "scene", "shot"}:
        raise _invalid("Unsupported creative context scope")
    project = (
        await session.execute(
            select(Project.id, Project.version)
            .where(
                Project.id == project_id,
            )
            .execution_options(autoflush=False)
        )
    ).one_or_none()
    if project is None:
        raise NotFoundError("Project not found")
    observed = {f"project:{project.id}": project.version}
    sources: list[dict[str, object]] = []
    shot = None
    scene_id = scope_entity_id
    if scope_type in {"project", "story"}:
        if scope_entity_id != project_id:
            raise NotFoundError("Creative scope not found")
    else:
        if scope_type == "shot":
            shot = (
                await session.execute(
                    select(
                        Shot.id,
                        Shot.scene_id,
                        Shot.version,
                        Shot.director_state,
                    )
                    .join(Scene, Scene.id == Shot.scene_id)
                    .join(
                        Episode,
                        Episode.id == Scene.episode_id,
                    )
                    .where(
                        Shot.id == scope_entity_id,
                        Shot.project_id == project_id,
                        Episode.project_id == project_id,
                    )
                    .execution_options(autoflush=False)
                )
            ).one_or_none()
            if shot is None:
                raise NotFoundError("Creative scope not found")
            scene_id = shot.scene_id
        scene = (
            await session.execute(
                select(
                    Scene.id,
                    Scene.version,
                    Scene.design_state,
                )
                .join(Episode, Episode.id == Scene.episode_id)
                .where(
                    Scene.id == scene_id,
                    Episode.project_id == project_id,
                )
                .execution_options(autoflush=False)
            )
        ).one_or_none()
        if scene is None:
            raise NotFoundError("Creative scope not found")
        sources.append(_source("scene", scene.id, scene.version, scene.design_state))
        observed[f"scene:{scene.id}"] = scene.version
        if shot is not None:
            sources.append(_source("shot", shot.id, shot.version, shot.director_state))
            observed[f"shot:{shot.id}"] = shot.version
    profile = (
        await session.execute(
            select(
                ProjectCreativeProfile.id,
                ProjectCreativeProfile.version,
                ProjectCreativeProfile.selected_genre,
                ProjectCreativeProfile.selected_style_ids,
                ProjectCreativeProfile.selected_skill_ids,
                ProjectCreativeProfile.selected_shot_language,
            )
            .where(ProjectCreativeProfile.project_id == project_id)
            .execution_options(autoflush=False)
        )
    ).one_or_none()
    selection: dict[str, object] = {
        "available": profile is not None,
        "profile_id": str(profile.id) if profile is not None else None,
        "profile_version": profile.version if profile is not None else None,
        "selected_genre": profile.selected_genre if profile is not None else None,
        "selected_style_ids": profile.selected_style_ids if profile is not None else [],
        "selected_skill_ids": profile.selected_skill_ids if profile is not None else [],
        "selected_shot_language": profile.selected_shot_language if profile is not None else None,
    }
    for key in ("selected_style_ids", "selected_skill_ids"):
        values = selection[key]
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise _invalid("Recorded creative selections must be lists of IDs")
    context: dict[str, object] = {
        "scope": {"type": scope_type, "id": str(scope_entity_id), "project_id": str(project_id)},
        "profile_selection": selection,
        "adopted_sources": sources,
        "adopted_available": any(source["available"] for source in sources),
        "observed_versions": observed,
    }
    context["context_hash"] = hashlib.sha256(_json(context).encode("utf-8")).hexdigest()
    encoded = _json(context)
    size = len(encoded.encode("utf-8"))
    if size > max_bytes:
        raise ValidationAppError(
            "Recorded creative context exceeds the byte limit; constraints were not truncated",
            details={
                "code": "DIRECTOR_CREATIVE_CONTEXT_TOO_LARGE",
                "required_bytes": size,
                "max_bytes": max_bytes,
            },
        )
    # JSON round-trip detaches nested ORM JSON values, including all style IDs.
    result = json.loads(encoded)
    assert isinstance(result, dict)
    return result
