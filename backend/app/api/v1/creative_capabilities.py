"""CC10 — creative capability REST surface (functional UI entries).

Exposes the frozen creative provenance, and a user-explicit freeze, onto
existing Scene/Shot state.  No Provider call and no second graph.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Episode, Scene, Shot
from app.director.creative_capabilities.contracts import CreativeSkillSpec
from app.director.creative_capabilities.creative_compiler import (
    CreativeCapabilityCompiler,
)
from app.director.creative_capabilities.freeze import (
    freeze_scene_capabilities,
    freeze_shot_capabilities,
)
from app.director.creative_capabilities.packs_library import (
    GENRE_PROFILES,
    STYLE_PACKS,
)
from app.director.creative_capabilities.shot_language_library import (
    QUALITY_POLICIES,
    SHOT_LANGUAGE_PACKS,
)
from app.shared.errors import ValidationAppError

router = APIRouter(
    tags=["creative-capabilities"], dependencies=[Depends(require_selected_workspace)]
)


class CapabilityCatalogBody(BaseModel):
    """The resolvable creative capability catalog (read-only)."""

    available_staged_strategies: list[str] = Field(default_factory=list)


class FreezeCreativeBody(BaseModel):
    """User-explicit creative capability selection to freeze."""

    genre_key: str | None = None
    style_key: str | None = None
    shot_language_key: str | None = None
    quality_policy_key: str | None = None
    skill_keys: list[str] = Field(default_factory=list)
    # Freeze target: a scene or a shot (exactly one).
    scene_id: UUID | None = None
    shot_id: UUID | None = None
    user_intent: dict[str, object] = Field(default_factory=dict)


class CreativeStateResponse(BaseModel):
    creative_capabilities: dict[str, object]
    target: str


@router.get(
    "/projects/{project_id}/creative-capabilities/catalog",
    response_model=CapabilityCatalogBody,
)
async def creative_capability_catalog(
    project_id: UUID,
    _user: CurrentUser,
    session: SessionDep,
) -> CapabilityCatalogBody:
    """Resolvable genre/style/shot-language/quality/skill catalog (read-only)."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=_user)
    return CapabilityCatalogBody(
        available_staged_strategies=[
            "two-pass-i2i-stabilize-v1",
            "lock-a-primary-then-i2i-b",
        ]
    )


def _frozen(state: dict[str, object] | None) -> dict[str, object]:
    """Extract the frozen ``creative_capabilities`` provenance if present."""
    value = (state or {}).get("creative_capabilities")
    return dict(value) if isinstance(value, dict) else {}


async def _scene_in_project(
    session: SessionDep, *, scene_id: UUID, project_id: UUID
) -> Scene:
    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise ValidationAppError("scene not found", details={"code": "SCENE_NOT_FOUND"})
    episode = await session.get(Episode, scene.episode_id)
    if episode is None or episode.project_id != project_id:
        raise ValidationAppError("scene not found", details={"code": "SCENE_NOT_FOUND"})
    return scene


@router.get("/projects/{project_id}/creative-capabilities/provenance")
async def creative_capability_provenance(
    project_id: UUID,
    _user: CurrentUser,
    session: SessionDep,
    scene_id: UUID | None = None,
    shot_id: UUID | None = None,
) -> CreativeStateResponse:
    """Read the frozen creative provenance from Scene/Shot state (read-only)."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=_user)
    if shot_id is not None:
        shot = await session.get(Shot, shot_id)
        if shot is None or shot.project_id != project_id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        return CreativeStateResponse(
            creative_capabilities=_frozen(shot.director_state), target="shot"
        )
    if scene_id is not None:
        scene = await _scene_in_project(session, scene_id=scene_id, project_id=project_id)
        return CreativeStateResponse(
            creative_capabilities=_frozen(scene.design_state), target="scene"
        )
    # Fall back to the first scene of the project as the default target.
    default_scene = await session.scalar(
        select(Scene)
        .join(Episode, Episode.id == Scene.episode_id)
        .where(Episode.project_id == project_id)
        .order_by(Scene.scene_number)
        .limit(1)
    )
    if default_scene is None:
        return CreativeStateResponse(creative_capabilities={}, target="none")
    return CreativeStateResponse(
        creative_capabilities=_frozen(default_scene.design_state), target="scene"
    )


@router.post(
    "/projects/{project_id}/creative-capabilities/freeze",
    response_model=CreativeStateResponse,
)
async def freeze_creative_capabilities(
    project_id: UUID,
    body: FreezeCreativeBody,
    _user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> CreativeStateResponse:
    """Freeze a user-explicit capability selection (never auto-applied)."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=_user)

    genre = next((g for g in GENRE_PROFILES if g.genre_key == body.genre_key), None)
    style = next((s for s in STYLE_PACKS if s.style_key == body.style_key), None)
    shot_language = next(
        (p for p in SHOT_LANGUAGE_PACKS if p.pack_key == body.shot_language_key), None
    )
    quality = next((q for q in QUALITY_POLICIES if q.policy_key == body.quality_policy_key), None)
    skills = [
        spec for spec in _skill_catalog() if spec.skill_key in body.skill_keys
    ]

    compiler = CreativeCapabilityCompiler()
    intent = compiler.compile(
        user_intent=body.user_intent,
        genre=genre,
        style=style,
        skill_stack=skills,
        shot_language=shot_language,
        quality_policy=quality,
    )

    if body.scene_id is not None:
        await freeze_scene_capabilities(
            session, project_id=project_id, scene_id=body.scene_id,
            intent=intent, actor_id=_user.id,
        )
        await session.commit()
        return CreativeStateResponse(creative_capabilities=intent.provenance, target="scene")
    if body.shot_id is not None:
        await freeze_shot_capabilities(
            session, project_id=project_id, shot_id=body.shot_id,
            intent=intent, actor_id=_user.id,
        )
        await session.commit()
        return CreativeStateResponse(creative_capabilities=intent.provenance, target="shot")
    raise ValidationAppError("freeze requires a scene_id or shot_id target")


def _skill_catalog() -> list[CreativeSkillSpec]:
    from app.director.creative_capabilities.skill_library import BASELINE_SKILLS

    return list(BASELINE_SKILLS)
