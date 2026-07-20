"""Creation experience routes (S1.5 shell)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.creation.service import CreationService
from app.shared.enums import ExperienceMode

router = APIRouter(tags=["creation"])


class StartProjectRequest(BaseModel):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=160)
    aspect_ratio: str = Field(pattern="^(9:16|16:9)$")
    experience_mode: ExperienceMode = ExperienceMode.QUICK


class StartProjectResponse(BaseModel):
    project_id: UUID
    experience_mode: ExperienceMode
    event_id: UUID
    outbox_id: UUID
    text_provider_operations: int


@router.post(
    "/creation/start-project",
    response_model=StartProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_project(
    body: StartProjectRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> StartProjectResponse:
    result = await CreationService(session).start_project(
        organization_id=body.organization_id,
        name=body.name,
        aspect_ratio=body.aspect_ratio,
        actor=user,
        experience_mode=body.experience_mode,
    )
    return StartProjectResponse(
        project_id=result["project_id"],
        experience_mode=ExperienceMode(result["experience_mode"]),
        event_id=result["event_id"],
        outbox_id=result["outbox_id"],
        text_provider_operations=result["text_provider_operations"],
    )
