"""Final Film HTTP routes bound to an OpenCut EditSession Timeline version."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, ConfigDict, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.production.final_film import (
    FinalFilmJobRead,
    FinalFilmPreparePreviewRead,
    FinalFilmPrepareRead,
    approve_preparation,
    get_final_film_status,
    list_final_film_jobs,
    prepare_formal_tail,
    preview_formal_tail,
    queue_final_film_render,
)

router = APIRouter(tags=["final-film"], dependencies=[Depends(require_selected_workspace)])


class FinalFilmPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_session_id: UUID
    expected_timeline_version: int = Field(ge=1)


class FinalFilmApproveBody(FinalFilmPreviewBody):
    preparation_fingerprint: str = Field(min_length=64, max_length=64)
    operation_keys: list[str] = Field(min_length=1)


class FinalFilmPrepareBody(FinalFilmPreviewBody):
    preparation_fingerprint: str = Field(min_length=64, max_length=64)
    command_authorization_ids: list[UUID]


class FinalFilmRenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_session_id: UUID
    expected_timeline_version: int = Field(ge=1)
    name: str = Field(default="V1 Final Film", min_length=1, max_length=200)


@router.post("/projects/{project_id}/final-film/prepare-authorizations", response_model=list[UUID])
async def confirm_final_film_operations(
    project_id: UUID, body: FinalFilmApproveBody, user: CurrentUser, session: SessionDep, _: CsrfDep
) -> list[UUID]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await approve_preparation(
        session, project_id=project_id, actor_id=user.id, **body.model_dump()
    )


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
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await prepare_formal_tail(
        session,
        project_id=project.id,
        edit_session_id=body.edit_session_id,
        expected_timeline_version=body.expected_timeline_version,
        actor_id=user.id,
        preparation_fingerprint=body.preparation_fingerprint,
        command_authorization_ids=body.command_authorization_ids,
    )


@router.post(
    "/projects/{project_id}/final-film/prepare-preview",
    response_model=FinalFilmPreparePreviewRead,
)
async def preview_final_film(
    project_id: UUID,
    body: FinalFilmPreviewBody,
    user: CurrentUser,
    session: SessionDep,
) -> FinalFilmPreparePreviewRead:
    """Read-only prepare preview: zero NodeRun, zero Provider call."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await preview_formal_tail(
        session,
        project_id=project.id,
        edit_session_id=body.edit_session_id,
        expected_timeline_version=body.expected_timeline_version,
    )


@router.post(
    "/projects/{project_id}/final-film/render",
    response_model=FinalFilmJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def render_final_film_route(
    project_id: UUID,
    body: FinalFilmRenderBody,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FinalFilmJobRead:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=body.edit_session_id,
        expected_timeline_version=body.expected_timeline_version,
        actor_id=user.id,
        idempotency_key=idempotency_key,
        name=body.name,
    )


@router.get(
    "/projects/{project_id}/edit-sessions/{session_id}/final-films",
    response_model=list[FinalFilmJobRead],
)
async def get_edit_session_final_films(
    project_id: UUID,
    session_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[FinalFilmJobRead]:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await list_final_film_jobs(session, project_id=project.id, edit_session_id=session_id)


@router.get(
    "/projects/{project_id}/final-film/runs/{node_run_id}",
    response_model=FinalFilmJobRead,
)
async def get_final_film_run_status(
    project_id: UUID,
    node_run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> FinalFilmJobRead:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await get_final_film_status(
        session,
        project_id=project.id,
        node_run_id=node_run_id,
    )


__all__ = ["router"]
