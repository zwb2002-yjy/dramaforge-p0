"""S3-style local invariants: cache hit, budget, cancel (in-process)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class NodeRun:
    id: UUID
    node_key: str
    input_hash: str
    status: str
    artifact_id: UUID | None = None
    provider_ops: int = 0
    cost: float = 0.0


@dataclass
class RuntimeState:
    budget_remaining: float = 100.0
    cache: dict[str, UUID] = field(default_factory=dict)
    runs: list[NodeRun] = field(default_factory=list)
    cancelled: set[UUID] = field(default_factory=set)


def run_node(
    state: RuntimeState,
    *,
    node_key: str,
    input_hash: str,
    cost: float,
    produce_artifact: bool = True,
) -> NodeRun:
    if state.budget_remaining < cost:
        run = NodeRun(
            id=uuid4(),
            node_key=node_key,
            input_hash=input_hash,
            status="blocked_budget",
            provider_ops=0,
            cost=0.0,
        )
        state.runs.append(run)
        return run
    cache_key = f"{node_key}:{input_hash}"
    if cache_key in state.cache:
        run = NodeRun(
            id=uuid4(),
            node_key=node_key,
            input_hash=input_hash,
            status="cached",
            artifact_id=state.cache[cache_key],
            provider_ops=0,
            cost=0.0,
        )
        state.runs.append(run)
        return run
    art = uuid4() if produce_artifact else None
    run = NodeRun(
        id=uuid4(),
        node_key=node_key,
        input_hash=input_hash,
        status="completed",
        artifact_id=art,
        provider_ops=1,
        cost=cost,
    )
    if art is not None:
        state.cache[cache_key] = art
    state.budget_remaining -= cost
    state.runs.append(run)
    return run


def cancel_run(state: RuntimeState, run_id: UUID) -> str:
    state.cancelled.add(run_id)
    for run in state.runs:
        if run.id == run_id and run.status in {"completed", "cached"}:
            return "completed_after_cancel"
        if run.id == run_id:
            run.status = "cancelled"
            return "cancelled"
    return "not_found"
