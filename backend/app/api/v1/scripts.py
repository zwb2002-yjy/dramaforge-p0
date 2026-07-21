"""Script import and shot listing API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.assets.models import Shot
from app.assets.script_import import import_script

router = APIRouter(tags=["scripts"])


class ScriptImportBody(BaseModel):
    filename: str = Field(min_length=1, max_length=260)
    text: str = Field(min_length=1)
    register_lead: bool = True


class ScriptImportResponse(BaseModel):
    script_document_id: UUID
    episode_id: UUID
    scene_count: int
    shot_count: int
    shot_ids: list[UUID]
    lead_character: str | None
    content_hash: str
    character_id: UUID | None = None
    canonical_object_key: str | None = None


class ShotRead(BaseModel):
    id: UUID
    scene_id: UUID
    shot_number: int
    shot_type: str
    visual_description: str
    dialogue: str
    sort_order: int
    status: str
    version: int


@router.post(
    "/projects/{project_id}/scripts/import",
    response_model=ScriptImportResponse,
)
async def import_project_script(
    project_id: UUID,
    body: ScriptImportBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ScriptImportResponse:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    result = await import_script(
        session,
        project_id=project_id,
        actor_id=user.id,
        filename=body.filename,
        text=body.text,
        actor=user,
    )
    character_id = None
    canon_key = None
    # Never silent-Fake canonical on import. Lead must be registered via
    # POST .../characters/lead (live Provider) or audited manual upload.
    if body.register_lead and result.lead_character:
        # Keep character name only — no Fake image generation
        pass
    await session.commit()
    return ScriptImportResponse(
        script_document_id=result.script_document_id,
        episode_id=result.episode_id,
        scene_count=result.scene_count,
        shot_count=result.shot_count,
        shot_ids=result.shot_ids,
        lead_character=result.lead_character,
        content_hash=result.content_hash,
        character_id=character_id,
        canonical_object_key=canon_key,
    )


@router.get("/projects/{project_id}/shots", response_model=list[ShotRead])
async def list_project_shots(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[ShotRead]:
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    rows = list(
        (
            await session.execute(
                select(Shot)
                .where(Shot.project_id == project_id)
                .order_by(Shot.sort_order, Shot.shot_number)
            )
        )
        .scalars()
        .all()
    )
    return [
        ShotRead(
            id=r.id,
            scene_id=r.scene_id,
            shot_number=r.shot_number,
            shot_type=r.shot_type,
            visual_description=r.visual_description,
            dialogue=r.dialogue,
            sort_order=r.sort_order,
            status=r.status,
            version=r.version,
        )
        for r in rows
    ]
