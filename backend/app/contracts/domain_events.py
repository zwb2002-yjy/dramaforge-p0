"""Versioned production notices; consumers re-read authoritative scoped facts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExecutionAccepted(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["execution_accepted"] = "execution_accepted"
    shot_id: UUID
    node_run_id: UUID


class ExecutionChanged(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["execution_changed"] = "execution_changed"
    shot_id: UUID
    node_run_id: UUID


class FormalSelected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["formal_selected"] = "formal_selected"
    shot_id: UUID
    shot_version: int = Field(ge=1)
    artifact_id: UUID
    stage: Literal["image_keyframe", "video"]


class ProposalDecided(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["proposal_decided"] = "proposal_decided"
    proposal_id: UUID


ProductionNotice = Annotated[
    ExecutionAccepted | ExecutionChanged | FormalSelected | ProposalDecided,
    Field(discriminator="kind"),
]


def notice_scope(notice: ProductionNotice) -> tuple[str, UUID]:
    if isinstance(notice, ProposalDecided):
        return "proposal", notice.proposal_id
    return "shot", notice.shot_id


class ProductionEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: UUID
    project_id: UUID
    actor_id: UUID
    payload: ProductionNotice
