"""Final Film HTTP routes bound to an OpenCut EditSession Timeline version."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.production.final_film import (
    FinalFilmPrepareRead,
    FinalFilmRead,
    prepare_formal_tail,
    render_final_film,
)

router = APIRouter(tags=["final-film"], dependencies=[Depends(require_selected_workspace)])


class FinalFilmPrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_session_id: UUID
    expected_timeline_version: int | None = Field(default=None, ge=1)
    mode: Literal["prepare"] = "prepare"


class FinalFilmRenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_session_id: UUID
    expected_timeline_version: int | None = Field(default=None, ge=1)
    name: str = Field(default="V1 Final Film", min_length=1, max_length=200)


@router.post(
    "/projects/{project_id}/final-film/prepare",
    response_model=FinalFilmPrepareRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def prepare_final_film(
    project_id: UUID,
    body: FinalFilmPrepareBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> FinalFilmPrepareRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    return await prepare_formal_tail(
        session,
        project_id=project.id,
        edit_session_id=body.edit_session_id,
        expected_timeline_version=body.expected_timeline_version,
        actor_id=user.id,
    )


@router.post(
    "/projects/{project_id}/final-film/render",
    response_model=FinalFilmRead,
)
async def render_final_film_route(
    project_id: UUID,
    body: FinalFilmRenderBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FinalFilmRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    return await render_final_film(
        session,
        project_id=project.id,
        edit_session_id=body.edit_session_id,
        expected_timeline_version=body.expected_timeline_version,
        actor_id=user.id,
        idempotency_key=idempotency_key,
        name=body.name,
    )


__all__ = ["router"]
