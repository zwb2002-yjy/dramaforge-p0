"""Engine-independent runtime control; never accept a caller's graph state."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RuntimeScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: UUID
    project_id: UUID
    actor_id: UUID


class RuntimeInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: RuntimeScope
    turn_id: UUID
    runtime_execution_id: UUID
    engine_version: str = Field(min_length=1, max_length=120)
    input_reference: UUID
    authorization_ref: UUID | None = None
    max_steps: int = Field(ge=1, le=100)


class ResumeSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: RuntimeScope
    turn_id: UUID
    signal_id: UUID
    reason: Literal["user_decision", "production_fact", "recovery"]
    reference_id: UUID
    expected_revision: int = Field(ge=1)


class StopRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: RuntimeScope
    turn_id: UUID
    request_id: UUID
    expected_revision: int = Field(ge=1)


class RuntimeView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    runtime_execution_id: UUID
    engine_version: str = Field(min_length=1, max_length=120)
    state_schema_version: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    step_count: int = Field(ge=0)
    status: Literal[
        "queued", "thinking", "awaiting_user", "awaiting_execution",
        "completed", "failed", "cancelled", "stale",
    ]
    wait_reason: str | None = None
    proposal_id: UUID | None = None
    dispatched_command_key: str | None = None
    node_run_ids: tuple[UUID, ...] = ()
