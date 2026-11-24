"""Worker-side adoption of one durably accepted Agent Turn.

The HTTP acceptance owns only durable facts. This module is the single
execution owner: it resolves the persisted project scope, opens the scoped
checkpoint store and asks the Agent service to adopt (compare-and-set) the
queued Turn. It never resumes an interrupted execution and never submits a
second text request for the same Turn.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.director.agent_service import DirectorAgentService
from app.director.runtime.checkpoint import scoped_checkpointer
from app.shared.db import resolve_agent_turn_rls_scope

ACCEPTED_STATUSES = frozenset({"queued"})


async def execute_accepted_agent_turn(
    factory: Callable[[], AsyncSession],
    *,
    turn_id: UUID,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Execute one accepted Turn, or report why it is not this worker's to run."""

    async with factory() as session:
        scope = await resolve_agent_turn_rls_scope(session, turn_id=turn_id)
    if scope is None:
        return {"status": "missing", "turn_id": str(turn_id)}
    service = DirectorAgentService(
        factory,
        actor_id=scope.user_id,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
    )
    current = await service.read_turn(turn_id)
    if current.status not in ACCEPTED_STATUSES:
        # A terminal Turn is a receipt; a thinking Turn belongs to another owner.
        return {"status": current.status, "turn_id": str(turn_id)}
    resolved = settings or get_settings()
    async with scoped_checkpointer(resolved, project_id=scope.project_id) as checkpointer:
        result = await service.execute_queued(turn_id, checkpointer=checkpointer)
    return {
        "status": result.status,
        "turn_id": str(result.turn_id),
        "transport_status": result.transport_status,
        "stop_reason": result.stop_reason,
    }


__all__ = ["execute_accepted_agent_turn"]
