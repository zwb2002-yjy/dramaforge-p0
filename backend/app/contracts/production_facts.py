"""Committed production projections; no ORM or director engine types."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ExecutionFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    project_id: UUID
    shot_id: UUID
    status: str
    stage: str
    result_artifact_id: UUID | None


class ProductionReadPort(Protocol):
    async def executions(
        self, *, project_id: UUID, shot_id: UUID, run_ids: tuple[UUID, ...],
    ) -> tuple[ExecutionFact, ...]:
        """Return all scoped links in requested order, or reject the entire read."""
        ...


class ExecutionTrackingFact(ExecutionFact):
    input_hash: str
    command_key: str
    shot_version: int | None
    model_resolution: dict[str, object]
