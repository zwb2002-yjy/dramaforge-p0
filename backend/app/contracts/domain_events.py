"""Versioned production notices; consumers re-read authoritative scoped facts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExecutionAccepted(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["execution_accepted"] = "execution_accepted"
    shot_id: UUID | None = None
    asset_id: UUID | None = None
    node_run_id: UUID

    @model_validator(mode="after")
    def require_single_target(self) -> "ExecutionAccepted":
        if (self.shot_id is None) == (self.asset_id is None):
            raise ValueError("execution notice requires exactly one target")
        return self


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


class ProjectChanged(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["project_changed"] = "project_changed"
    project_id: UUID
    project_version: int = Field(ge=1)


class MasterRunChanged(BaseModel):
    """Control/state change of one continuous goal; no goal text or plan body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["master_run_changed"] = "master_run_changed"
    run_id: UUID
    revision: int = Field(ge=1)
    status: str
    desired_state: str
    control_epoch: int = Field(ge=0)


class MasterRunPlanProposed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["master_run_plan_proposed"] = "master_run_plan_proposed"
    run_id: UUID
    plan_id: UUID
    plan_revision: int = Field(ge=1)
    decision_ref: UUID


class MasterRunPlanApplied(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["master_run_plan_applied"] = "master_run_plan_applied"
    run_id: UUID
    plan_id: UUID
    plan_revision: int = Field(ge=1)
    applied_run_revision: int = Field(ge=1)
    control_epoch: int = Field(ge=0)


class BusinessFlowChanged(BaseModel):
    """Flow instance progress; no input body, tool arguments or receipts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["business_flow_changed"] = "business_flow_changed"
    run_id: UUID
    instance_id: UUID
    revision: int = Field(ge=1)
    status: str


class BusinessStepChanged(BaseModel):
    """Step progress inside one flow instance; attempts are read through it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["business_step_changed"] = "business_step_changed"
    instance_id: UUID
    step_id: UUID
    revision: int = Field(ge=1)
    status: str


class ProjectEgressPolicyChanged(BaseModel):
    """One committed policy revision; no destination origins or payload summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["project_egress_policy_changed"] = "project_egress_policy_changed"
    project_id: UUID
    policy_revision: int = Field(ge=1)


ProductionNotice = Annotated[
    ExecutionAccepted | ExecutionChanged | FormalSelected | ProposalDecided | ProjectChanged
    | MasterRunChanged | MasterRunPlanProposed | MasterRunPlanApplied
    | BusinessFlowChanged | BusinessStepChanged
    | ProjectEgressPolicyChanged,
    Field(discriminator="kind"),
]


def notice_scope(notice: ProductionNotice) -> tuple[str, UUID]:
    if isinstance(notice, ProjectChanged):
        return "project", notice.project_id
    if isinstance(notice, ProjectEgressPolicyChanged):
        return "project_egress_policy", notice.project_id
    if isinstance(notice, ProposalDecided):
        return "proposal", notice.proposal_id
    if isinstance(notice, (MasterRunChanged, MasterRunPlanProposed, MasterRunPlanApplied)):
        return "master_run", notice.run_id
    if isinstance(notice, BusinessFlowChanged):
        return "business_flow", notice.instance_id
    if isinstance(notice, BusinessStepChanged):
        return "business_step", notice.step_id
    if isinstance(notice, ExecutionAccepted) and notice.asset_id is not None:
        return "asset", notice.asset_id
    if notice.shot_id is None:
        raise ValueError("production notice has no target")
    return "shot", notice.shot_id


class ProductionEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: UUID
    project_id: UUID
    actor_id: UUID
    payload: ProductionNotice
