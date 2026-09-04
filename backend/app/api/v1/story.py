"""Proposal-first Story authoring API (V1 G1).

Creating a proposal never writes Canonical Story facts.  Preview returns the
typed operation list; apply executes only user-accepted items through the
shared ProposalCommandRegistry.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.proposal_service import (
    PartialApplyInput,
    PartialApplyResult,
    ProposalService,
)
from app.director.story_proposal import create_story_proposal
from app.shared.errors import NotFoundError

router = APIRouter(tags=["story"], dependencies=[Depends(require_selected_workspace)])


class StoryProposalCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=160)
    brief: str = Field(default="", max_length=8000)
    filename: str = Field(default="story-draft.md", min_length=1, max_length=260)
    draft_text: str = Field(min_length=1, max_length=200_000)


class StoryOperationRead(BaseModel):
    id: UUID
    command: str
    action: str
    key: str
    expected_target_version: int | None
    rationale: str
    impact: str
    payload: dict[str, object]


class StoryProposalRead(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    summary: str
    created_at: datetime
    operations: list[StoryOperationRead]


def _operation_read(item: DirectorProposalItem) -> StoryOperationRead:
    payload = dict(item.payload or {})
    return StoryOperationRead(
        id=item.id,
        command=item.command,
        action=str(payload.get("action") or "create"),
        key=str(payload.get("key") or item.command),
        expected_target_version=item.expected_target_version,
        rationale=item.rationale,
        impact=item.impact,
        payload=payload,
    )


async def _proposal_read(
    session: SessionDep,
    *,
    project_id: UUID,
    proposal: DirectorProposal,
) -> StoryProposalRead:
    items = list(
        (
            await session.execute(
                select(DirectorProposalItem)
                .where(DirectorProposalItem.proposal_id == proposal.id)
                .order_by(DirectorProposalItem.created_at, DirectorProposalItem.id)
            )
        )
        .scalars()
        .all()
    )
    items.sort(
        key=lambda item: int(str((item.payload or {}).get("sort_order") or 0))
    )
    return StoryProposalRead(
        id=proposal.id,
        project_id=project_id,
        status=proposal.status,
        summary=(
            "Story authoring proposal: script draft → typed Canonical Story diff"
        ),
        created_at=proposal.created_at,
        operations=[_operation_read(item) for item in items],
    )


@router.post(
    "/projects/{project_id}/story/proposals",
    response_model=StoryProposalRead,
    status_code=201,
)
async def create_project_story_proposal(
    project_id: UUID,
    body: StoryProposalCreateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> StoryProposalRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    result = await create_story_proposal(
        session,
        project_id=project.id,
        actor=user,
        brief=body.brief,
        filename=body.filename,
        draft_text=body.draft_text,
        idempotency_key=body.idempotency_key,
    )
    await session.commit()
    return await _proposal_read(session, project_id=project.id, proposal=result.proposal)


@router.get(
    "/projects/{project_id}/story/proposals",
    response_model=list[StoryProposalRead],
)
async def list_project_story_proposals(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[StoryProposalRead]:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    proposals = list(
        (
            await session.execute(
                select(DirectorProposal)
                .where(
                    DirectorProposal.project_id == project.id,
                    DirectorProposal.scope_type == "project",
                )
                .order_by(DirectorProposal.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        await _proposal_read(session, project_id=project.id, proposal=proposal)
        for proposal in proposals
    ]


@router.get(
    "/projects/{project_id}/story/proposals/{proposal_id}",
    response_model=StoryProposalRead,
)
async def get_project_story_proposal(
    project_id: UUID,
    proposal_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> StoryProposalRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    proposal = await session.scalar(
        select(DirectorProposal).where(
            DirectorProposal.id == proposal_id,
            DirectorProposal.project_id == project.id,
            DirectorProposal.scope_type == "project",
        )
    )
    if proposal is None:
        raise NotFoundError("story proposal not found")
    return await _proposal_read(session, project_id=project.id, proposal=proposal)


@router.post(
    "/projects/{project_id}/story/proposals/{proposal_id}/apply",
    response_model=PartialApplyResult,
)
async def apply_project_story_proposal(
    project_id: UUID,
    proposal_id: UUID,
    body: PartialApplyInput,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> PartialApplyResult:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    proposal = await session.scalar(
        select(DirectorProposal).where(
            DirectorProposal.id == proposal_id,
            DirectorProposal.project_id == project.id,
        )
    )
    if proposal is None:
        raise NotFoundError("story proposal not found")

    # Retrying an applied proposal is idempotent.
    if proposal.status in {"applied", "decided"}:
        items = list(
            (
                await session.execute(
                    select(DirectorProposalItem).where(
                        DirectorProposalItem.proposal_id == proposal.id
                    )
                )
            )
            .scalars()
            .all()
        )
        return PartialApplyResult(
            accepted=[
                item.id for item in items if item.status == "accepted"
            ],
            rejected=[
                item.id for item in items if item.status == "rejected"
            ],
            failed=[],
        )

    service = ProposalService(session, actor=user)
    result = await service.partial_apply(
        project=project,
        proposal_id=proposal.id,
        apply_input=body,
    )
    await session.commit()
    return result


__all__ = ["router"]
