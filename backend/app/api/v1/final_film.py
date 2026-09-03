"""Final Film HTTP routes for Formal Shot tails and playable Artifact export."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
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

    shot_ids: list[UUID] | None = Field(default=None, max_length=200)
    mode: Literal["prepare"] = "prepare"


class FinalFilmRenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
        actor=user,
        shot_ids=body.shot_ids,
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
) -> FinalFilmRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    return await render_final_film(
        session,
        project_id=project.id,
        actor=user,
        name=body.name,
    )


__all__ = ["router"]
