"""CC10 — creative capability REST surface (functional UI entries).

Exposes the frozen creative provenance, and a user-explicit freeze, onto
existing Scene/Shot state.  No Provider call and no second graph.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Episode, Scene, Shot
from app.director.creative_capabilities.composer import (
    CreativeSkillComposer,
    ResolutionStatus,
)
from app.director.creative_capabilities.contracts import CreativeSkillSpec
from app.director.creative_capabilities.creative_compiler import (
    CreativeCapabilityCompiler,
)
from app.director.creative_capabilities.freeze import (
    freeze_scene_capabilities,
    freeze_shot_capabilities,
    serialize_compiled_creative_intent,
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

    model_config = ConfigDict(extra="forbid")

    genre_key: str | None = None
    style_key: str | None = None
    shot_language_key: str | None = None
    quality_policy_key: str | None = None
    skill_keys: list[str] = Field(default_factory=list)
    # Freeze target: a scene or a shot (exactly one).
    scene_id: UUID | None = None
    shot_id: UUID | None = None
    user_intent: dict[str, object] = Field(default_factory=dict)
    accepted_proposal: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_exactly_one_target(self) -> FreezeCreativeBody:
        if (self.scene_id is None) == (self.shot_id is None):
            raise ValueError("freeze requires exactly one of scene_id or shot_id")
        return self


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


async def _scene_in_project(session: SessionDep, *, scene_id: UUID, project_id: UUID) -> Scene:
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
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=_user
    )

    genre = next((g for g in GENRE_PROFILES if g.genre_key == body.genre_key), None)
    style = next((s for s in STYLE_PACKS if s.style_key == body.style_key), None)
    shot_language = next(
        (p for p in SHOT_LANGUAGE_PACKS if p.pack_key == body.shot_language_key), None
    )
    quality = next((q for q in QUALITY_POLICIES if q.policy_key == body.quality_policy_key), None)
    for requested, resolved, kind in (
        (body.genre_key, genre, "genre"),
        (body.style_key, style, "style"),
        (body.shot_language_key, shot_language, "shot_language"),
        (body.quality_policy_key, quality, "quality_policy"),
    ):
        if requested is not None and resolved is None:
            raise ValidationAppError(
                f"unknown creative {kind}: {requested}",
                details={"code": "CREATIVE_CAPABILITY_UNAVAILABLE", "kind": kind},
            )
    skill_catalog = {spec.skill_key: spec for spec in _skill_catalog()}
    if len(body.skill_keys) != len(set(body.skill_keys)):
        raise ValidationAppError(
            "skill_keys must be unique",
            details={"code": "CREATIVE_SKILL_SELECTION_INVALID"},
        )
    missing_skills = [key for key in body.skill_keys if key not in skill_catalog]
    if missing_skills:
        raise ValidationAppError(
            f"unknown creative skill: {missing_skills[0]}",
            details={
                "code": "CREATIVE_CAPABILITY_UNAVAILABLE",
                "kind": "skill",
                "skill_key": missing_skills[0],
            },
        )
    composition = CreativeSkillComposer().compose(
        skills=[skill_catalog[key] for key in body.skill_keys]
    )
    if composition.status is ResolutionStatus.CONFLICT:
        raise ValidationAppError(
            "selected creative skills conflict",
            details={
                "code": "CREATIVE_SKILL_CONFLICT",
                "conflicts": composition.conflicts,
            },
        )

    saved_user_intent: dict[str, object] = {}
    if body.scene_id is not None:
        scene = await _scene_in_project(
            session,
            scene_id=body.scene_id,
            project_id=project_id,
        )
        saved_user_intent = dict(scene.design_state or {})
    elif body.shot_id is not None:
        shot = await session.get(Shot, body.shot_id)
        if shot is None or shot.project_id != project_id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        saved_user_intent = dict(shot.director_state or {})
        saved_user_intent.update(
            {
                "image_prompt": shot.image_prompt,
                "video_prompt": shot.video_prompt,
            }
        )
    saved_user_intent.pop("creative_capabilities", None)
    confirmed_user_intent = {**saved_user_intent, **body.user_intent}

    compiler = CreativeCapabilityCompiler()
    intent = compiler.compile(
        user_intent=confirmed_user_intent,
        accepted_proposal=body.accepted_proposal,
        project_context=dict(project.style_bible or {}),
        genre=genre,
        style=style,
        skill_stack=composition.stack,
        shot_language=shot_language,
        quality_policy=quality,
    )

    if body.scene_id is not None:
        await freeze_scene_capabilities(
            session,
            project_id=project_id,
            scene_id=body.scene_id,
            intent=intent,
            actor_id=_user.id,
        )
        await session.commit()
        return CreativeStateResponse(
            creative_capabilities=serialize_compiled_creative_intent(intent),
            target="scene",
        )
    if body.shot_id is not None:
        await freeze_shot_capabilities(
            session,
            project_id=project_id,
            shot_id=body.shot_id,
            intent=intent,
            actor_id=_user.id,
        )
        await session.commit()
        return CreativeStateResponse(
            creative_capabilities=serialize_compiled_creative_intent(intent),
            target="shot",
        )
    raise ValidationAppError("freeze requires a scene_id or shot_id target")


def _skill_catalog() -> list[CreativeSkillSpec]:
    from app.director.creative_capabilities.skill_library import BASELINE_SKILLS

    return list(BASELINE_SKILLS)
