"""Narrow Agent proposals; the harness owns the atomic tool receipt transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.agent_read_service import AgentReadService
from app.director.assistant_models import DirectorThread
from app.director.proposal_creation import ProposalItemDraft, create_proposal
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

if TYPE_CHECKING:
    from app.director.agent_tools import ToolContext


class ShotPromptProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shot_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    image_prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    video_prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    rationale: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def exactly_one_prompt(self) -> Self:
        if (self.image_prompt is None) == (self.video_prompt is None):
            raise ValueError("Provide exactly one of image_prompt and video_prompt.")
        prompt = self.image_prompt if self.image_prompt is not None else self.video_prompt
        if not prompt or not prompt.strip() or not self.rationale.strip():
            raise ValueError("Prompt and rationale must not be blank.")
        return self


class AgentProposalRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_ids: list[UUID]
    target_shot_id: UUID
    status: Literal["pending"] = "pending"
    requires_apply: Literal[True] = True
    observed_versions: dict[str, int]


async def create_agent_shot_proposal(
    session: AsyncSession,
    *,
    context: ToolContext,
    arguments: dict[str, object],
    call_id: str,
) -> AgentProposalRead:
    """Flush a pending proposal only; do not commit, Apply or execute production.

    Caller MUST hold the Turn lease/lock and atomically store the unique tool
    receipt keyed by turn + call_id with this proposal. A replay reads that
    receipt; it must not call this function again. No parallel proposal journal.
    """
    if not call_id or len(call_id) > 200:
        raise ValidationAppError("Invalid tool call identity")
    inputs = ShotPromptProposalInput.model_validate(arguments)
    reader = AgentReadService(
        session,
        actor_id=context.actor_id,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
    )
    project = await reader.project()
    thread = await session.scalar(
        select(DirectorThread).where(
            DirectorThread.id == context.thread_id,
            DirectorThread.project_id == context.project_id,
            DirectorThread.created_by == context.actor_id,
        )
    )
    if thread is None:
        raise NotFoundError("Director thread not found")
    if thread.scope_type != context.scope_type or thread.scope_entity_id != context.scope_entity_id:
        raise ValidationAppError("Thread scope changed", details={"code": "ToolPermissionDenied"})
    shot = await reader.shot(inputs.shot_id)
    observed = {f"project:{project.id}": project.version, f"shot:{shot.id}": shot.version}
    if context.scope_type in {"project", "story"}:
        allowed = context.scope_entity_id == project.id
    elif context.scope_type == "scene":
        scene = await reader.scene(context.scope_entity_id)
        observed[f"scene:{scene.id}"] = scene.version
        allowed = shot.scene_id == scene.id
    else:
        allowed = context.scope_entity_id == shot.id
    if not allowed:
        raise ValidationAppError(
            "Shot is outside the current scope", details={"code": "ToolPermissionDenied"}
        )
    if shot.version != inputs.expected_version or any(
        context.expected_versions[key] != version
        for key, version in observed.items()
        if key in context.expected_versions
    ):
        raise ConflictError(
            "Context changed; read the target again",
            details={"code": "ContextStale"},
        )
    field = "image_prompt" if inputs.image_prompt is not None else "video_prompt"
    prompt = inputs.image_prompt if inputs.image_prompt is not None else inputs.video_prompt
    proposal, _ = await create_proposal(
        session,
        thread=thread,
        scope_type="shot",
        scope_entity_id=shot.id,
        created_by=context.actor_id,
        items=[
            ProposalItemDraft(
                command=f"shot.update_{field}",
                payload={"shot_id": str(shot.id), field: prompt},
                expected_target_version=shot.version,
                rationale=inputs.rationale,
            )
        ],
    )
    return AgentProposalRead(
        proposal_ids=[proposal.id], target_shot_id=shot.id, observed_versions=observed
    )
