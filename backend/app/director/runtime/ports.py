"""Application runtime boundary; adapters own scheduling and deduplication."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.contracts.director_runtime import (
    ResumeSignal,
    RuntimeInput,
    RuntimeScope,
    RuntimeView,
    StopRequest,
)
from app.contracts.production_commands import ExecutionReceipt
from app.contracts.production_facts import ExecutionFact


class RuntimeProposalFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID | None
    proposal_version: int
    command_key: str | None = None
    persisted_decision: Literal["accept", "reject"] | None = None
    next_action: Literal["complete", "execute"] = "complete"


class RuntimeDecisionFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["accept", "reject"]
    decision_version: int
    next_action: Literal["complete", "execute"] = "execute"


class DirectorRuntimeToolPort(Protocol):
    async def propose(self, request: RuntimeInput) -> RuntimeProposalFact: ...

    async def decision(self, signal: ResumeSignal) -> RuntimeDecisionFact: ...

    async def submit_execution(
        self,
        *,
        request: RuntimeInput,
        proposal: RuntimeProposalFact,
        command_key: str,
    ) -> ExecutionReceipt: ...

    async def execution_fact(self, signal: ResumeSignal) -> ExecutionFact: ...


class RuntimeResumeClaimPort(Protocol):
    async def claim(self, signal: ResumeSignal) -> bool:
        """Persist one signal claim; False means another worker already owns it."""
        ...


class DirectorRuntimePort(Protocol):
    async def start(self, request: RuntimeInput) -> RuntimeView:
        """Persist acceptance and schedule the bounded turn, returning promptly."""
        ...

    async def resume(self, signal: ResumeSignal) -> RuntimeView:
        """Validate persisted facts/decisions and deduplicate the durable signal."""
        ...

    async def request_stop(self, request: StopRequest) -> RuntimeView:
        """Persist a control request; never imply cancellation of a NodeRun."""
        ...

    async def read(self, *, scope: RuntimeScope, turn_id: UUID) -> RuntimeView:
        """Authorize scope before exposing the application projection."""
        ...


__all__ = [
    "DirectorRuntimePort",
    "DirectorRuntimeToolPort",
    "RuntimeDecisionFact",
    "RuntimeProposalFact",
    "RuntimeResumeClaimPort",
]
