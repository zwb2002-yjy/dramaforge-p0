"""Project egress policy HTTP: read the current permission set and commit revisions."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.access.models import Project, User
from app.access.project_data_policy import ProjectDataPolicy
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.contracts.domain_events import ProjectEgressPolicyChanged
from app.production.application.events import append_production_notice

router = APIRouter(tags=["project-egress"], dependencies=[Depends(require_selected_workspace)])

EgressMode = Literal["current", "local_only", "allowlisted"]


class EgressPolicyRead(BaseModel):
    revision: int
    revision_id: UUID | None
    mode: EgressMode
    allowed_destination_revision_ids: list[str]
    allowed_purposes: list[str]
    policy_hash: str | None


class EgressPolicyPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0, strict=True)
    mode: EgressMode
    allowed_destination_revision_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_purposes: list[str] = Field(default_factory=list, max_length=100)


async def _policy(
    project_id: UUID, user: User, session: SessionDep,
) -> tuple[Project, ProjectDataPolicy]:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return project, ProjectDataPolicy(session, actor=user, project=project)


@router.get("/projects/{project_id}/egress-policy", response_model=EgressPolicyRead)
async def read_egress_policy(
    project_id: UUID, user: CurrentUser, session: SessionDep,
) -> EgressPolicyRead:
    _project, policy = await _policy(project_id, user, session)
    return EgressPolicyRead.model_validate(await policy.read())


@router.put("/projects/{project_id}/egress-policy", response_model=EgressPolicyRead)
async def put_egress_policy(
    project_id: UUID,
    body: EgressPolicyPut,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> EgressPolicyRead:
    project, policy = await _policy(project_id, user, session)
    revision = await policy.put(
        expected_revision=body.expected_revision,
        mode=body.mode,
        allowed_destination_revision_ids=body.allowed_destination_revision_ids,
        allowed_purposes=body.allowed_purposes,
    )
    await append_production_notice(
        session, project_id=project.id, actor_id=user.id,
        notice=ProjectEgressPolicyChanged(
            project_id=project.id, policy_revision=revision.revision,
        ),
    )
    await session.commit()
    return EgressPolicyRead.model_validate(await policy.read())


__all__ = ["router"]
