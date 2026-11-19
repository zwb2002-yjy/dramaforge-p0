"""Research-analysis Turn worker: claim one frozen Turn, run it, publish the manifest.

The Turn row is the durable work item; this worker never creates a second queue or
runtime. A failed execution marks the Turn failed (bounded error code only) and keeps
the original evidence for review; it is never silently retried.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.director.research_import import ResearchImportService
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.shared.db import set_rls_context
from app.shared.errors import AppError
from app.shared.rls_scopes import (
    DirectorTurnRlsScope,
    resolve_research_turn_rls_scope,
)

logger = logging.getLogger(__name__)


async def execute_research_analysis(
    factory: Callable[[], AsyncSession], *, turn_id: UUID
) -> dict[str, object]:
    async with factory() as probe:
        scope = await resolve_research_turn_rls_scope(probe, turn_id=turn_id)
    if scope is None:
        return {"status": "skipped", "reason": "unknown_research_turn"}
    async with factory() as session:
        await set_rls_context(
            session,
            user_id=scope.user_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
        )
        session.info["selected_workspace_id"] = scope.workspace_id
        turn = await session.get(DirectorTurn, turn_id)
        project = await session.get(Project, scope.project_id)
        actor = await session.get(User, scope.user_id)
        if turn is None or project is None or actor is None or not actor.is_active:
            return {"status": "skipped", "reason": "missing_scope_facts"}
        if turn.status != "queued":
            return {"status": "skipped", "reason": "not_queued", "turn_status": turn.status}
        try:
            claimed = await DirectorTurnService(session).claim(
                project_id=scope.project_id,
                turn_id=turn_id,
                expected_revision=turn.revision,
            )
        except AppError as exc:
            await session.rollback()
            return {"status": "not_claimable", "code": exc.code}
        await session.commit()
        try:
            publication = await ResearchImportService(session).execute(
                project=project, actor=actor, turn=claimed
            )
            await session.commit()
            return {"status": "published", "analysis_id": str(publication.analysis_id)}
        except Exception as exc:  # noqa: BLE001 - bounded failure receipt, no retry
            await session.rollback()
            logger.warning("Research analysis %s failed (%s)", turn_id, type(exc).__name__)
            await _record_failure(factory, turn_id=turn_id, scope=scope, error=type(exc).__name__)
            return {"status": "failed", "error": type(exc).__name__}


async def _record_failure(
    factory: Callable[[], AsyncSession],
    *,
    turn_id: UUID,
    scope: DirectorTurnRlsScope,
    error: str,
) -> None:
    async with factory() as session:
        await set_rls_context(
            session,
            user_id=scope.user_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
        )
        session.info["selected_workspace_id"] = scope.workspace_id
        turn = await session.get(DirectorTurn, turn_id)
        if turn is None or turn.status != "thinking":
            return
        await DirectorTurnService(session).compare_and_set(
            turn=turn,
            expected_statuses=("thinking",),
            target_status="failed",
            updates={
                "last_error": error,
                "wait_reason": "analysis_failed",
                "transport_status": "failed",
            },
        )
        await session.commit()


__all__ = ["execute_research_analysis"]
