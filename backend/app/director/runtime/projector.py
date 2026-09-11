"""Project engine progress onto DirectorTurn without copying business truth."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.director_runtime import RuntimeView
from app.director.turn_models import DirectorTurn
from app.director.turn_service import TERMINAL_TURN_STATUSES, DirectorTurnService
from app.shared.errors import ConflictError, NotFoundError


class DirectorRuntimeProjector:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._turns = DirectorTurnService(session)

    async def project(self, view: RuntimeView) -> DirectorTurn:
        turn = await self._session.scalar(
            select(DirectorTurn).where(
                DirectorTurn.id == view.turn_id,
                DirectorTurn.runtime_execution_id == view.runtime_execution_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if turn is None:
            raise NotFoundError("Director runtime binding not found")
        if (
            turn.engine_version != view.engine_version
            or turn.state_schema_version != view.state_schema_version
        ):
            raise ConflictError(
                "Director runtime projection version differs from its immutable binding",
                details={"code": "DIRECTOR_ENGINE_BINDING_CONFLICT"},
            )
        if turn.runtime_revision is not None:
            if turn.runtime_revision > view.revision:
                raise ConflictError(
                    "Director runtime projection is stale",
                    details={"code": "DIRECTOR_RUNTIME_PROJECTION_STALE"},
                )
            if turn.runtime_revision == view.revision:
                if (
                    turn.status != view.status
                    or turn.wait_reason != view.wait_reason
                    or turn.dispatched_command_key != view.dispatched_command_key
                    or [str(item) for item in turn.node_run_ids]
                    != [str(item) for item in view.node_run_ids]
                ):
                    raise ConflictError(
                        "Director runtime revision has a different projection",
                        details={"code": "DIRECTOR_RUNTIME_PROJECTION_CONFLICT"},
                    )
                return turn
        if turn.status in TERMINAL_TURN_STATUSES and turn.status != view.status:
            raise ConflictError(
                "Director runtime cannot revive a terminal Turn",
                details={"code": "DIRECTOR_RUNTIME_TERMINAL_PROJECTION"},
            )
        updates: dict[str, object] = {
            "wait_reason": view.wait_reason,
            "node_run_ids": [str(run_id) for run_id in view.node_run_ids],
            "dispatched_command_key": view.dispatched_command_key,
            "runtime_revision": view.revision,
            "step_count": view.step_count,
        }
        if view.proposal_id is not None:
            updates["proposal_id"] = view.proposal_id
        return await self._turns.compare_and_set(
            turn=turn,
            expected_statuses=(turn.status,),
            target_status=view.status,
            updates=updates,
        )


__all__ = ["DirectorRuntimeProjector"]
