"""Reconcile waiting runtime turns from canonical production facts."""

from __future__ import annotations

from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.director_runtime import ResumeSignal, RuntimeScope
from app.director.runtime.models import DirectorRuntimeWakeup
from app.director.runtime.wakeups import DirectorRuntimeWakeupService
from app.director.turn_models import DirectorTurn
from app.events.models import EventLog
from app.production.application.facts import ProductionFacts

_SUCCESS = frozenset(
    {"succeeded", "completed", "cached", "completed_after_cancel", "late_completed"}
)
_FAILURE = frozenset({"failed", "cancelled"})


class DirectorRuntimeFactReconciler:
    """Schedule the next durable signal from facts already committed by the app."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reconcile(self, turn: DirectorTurn) -> DirectorRuntimeWakeup | None:
        if (
            turn.runtime_execution_id is None
            or turn.runtime_revision is None
            or len(turn.node_run_ids or []) != 1
        ):
            return None
        run_id = UUID(str(turn.node_run_ids[0]))
        tracking = await ProductionFacts(self._session).tracking(
            project_id=turn.project_id,
            run_id=run_id,
        )
        reason: Literal["production_fact", "user_decision"]
        event: EventLog | None
        if turn.status == "awaiting_execution" and tracking.status in _SUCCESS | _FAILURE:
            reason = "production_fact"
            event = await self._execution_event(turn, run_id=run_id)
        elif turn.status == "awaiting_user" and turn.wait_reason == "confirm_candidate":
            if tracking.result_artifact_id is None:
                return None
            reason = "user_decision"
            event = await self._formal_event(
                turn,
                artifact_id=tracking.result_artifact_id,
                stage=tracking.stage,
            )
        else:
            return None
        if event is None:
            return None
        signal = ResumeSignal(
            scope=RuntimeScope(
                workspace_id=turn.workspace_id,
                project_id=turn.project_id,
                actor_id=turn.actor_id,
            ),
            turn_id=turn.id,
            signal_id=uuid5(
                NAMESPACE_URL,
                f"dramaforge:runtime-reconcile:{turn.runtime_execution_id}:"
                f"{turn.runtime_revision}:{event.event_id}:{reason}",
            ),
            reason=reason,
            reference_id=event.event_id,
            expected_revision=turn.runtime_revision,
        )
        return await DirectorRuntimeWakeupService(self._session).enqueue_resume(
            signal,
            runtime_execution_id=turn.runtime_execution_id,
        )

    async def _execution_event(self, turn: DirectorTurn, *, run_id: UUID) -> EventLog | None:
        return (
            await self._session.scalars(
                select(EventLog)
                .where(
                    EventLog.project_id == turn.project_id,
                    EventLog.actor_id == turn.actor_id,
                    EventLog.event_type == "execution_changed",
                    EventLog.payload["notice"]["node_run_id"].as_string() == str(run_id),
                )
                .order_by(EventLog.occurred_at.desc(), EventLog.event_id.desc())
                .limit(1)
            )
        ).first()

    async def _formal_event(
        self,
        turn: DirectorTurn,
        *,
        artifact_id: UUID,
        stage: str,
    ) -> EventLog | None:
        return (
            await self._session.scalars(
                select(EventLog)
                .where(
                    EventLog.project_id == turn.project_id,
                    EventLog.actor_id == turn.actor_id,
                    EventLog.event_type == "formal_selected",
                    EventLog.payload["notice"]["shot_id"].as_string() == str(turn.scope_entity_id),
                    EventLog.payload["notice"]["artifact_id"].as_string() == str(artifact_id),
                    EventLog.payload["notice"]["stage"].as_string() == stage,
                )
                .order_by(EventLog.occurred_at.desc(), EventLog.event_id.desc())
                .limit(1)
            )
        ).first()


__all__ = ["DirectorRuntimeFactReconciler"]
