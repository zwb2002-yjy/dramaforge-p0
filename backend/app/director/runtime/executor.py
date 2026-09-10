"""Fenced execution of one LangGraph step across durable boundaries."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.contracts.director_runtime import (
    ResumeSignal,
    RuntimeInput,
    RuntimeScope,
    RuntimeView,
    StopRequest,
)
from app.director.runtime.checkpoint import scoped_checkpointer
from app.director.runtime.control import DirectorRuntimeControlService, RuntimeLease
from app.director.runtime.langgraph_adapter import LangGraphDirectorRuntime
from app.director.runtime.ports import DirectorRuntimeToolPort
from app.director.runtime.projector import DirectorRuntimeProjector
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, NotFoundError


class _AcceptedResumeClaim:
    """The business journal was committed before entering the graph."""

    def __init__(self, signal_id: UUID) -> None:
        self._signal_id = signal_id

    async def claim(self, signal: ResumeSignal) -> bool:
        if signal.signal_id != self._signal_id:
            raise ConflictError(
                "Director runtime received an unjournaled signal",
                details={"code": "DIRECTOR_RESUME_SIGNAL_UNJOURNALED"},
            )
        return True


class DirectorRuntimeExecutor:
    """Own app/checkpoint transaction ordering for a single worker operation."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        tools: DirectorRuntimeToolPort,
        worker_id: str,
    ) -> None:
        self._session = session
        self._settings = settings
        self._tools = tools
        self._worker_id = worker_id
        self._controls = DirectorRuntimeControlService(session)
        self._projector = DirectorRuntimeProjector(session)

    async def start(self, request: RuntimeInput) -> RuntimeView:
        turn = await self._bound_turn(
            scope=request.scope,
            turn_id=request.turn_id,
            runtime_execution_id=request.runtime_execution_id,
        )
        if turn.status == "queued":
            await DirectorTurnService(self._session).claim(
                project_id=turn.project_id,
                turn_id=turn.id,
                expected_revision=turn.revision,
            )
            await self._session.commit()
            await self._restore_scope(request.scope)
        lease = await self._claim(request.scope, request.runtime_execution_id)
        try:
            async with self._controls.guard(lease):
                async with scoped_checkpointer(
                    self._settings, project_id=request.scope.project_id,
                ) as saver:
                    runtime = LangGraphDirectorRuntime(
                        checkpointer=saver,
                        tools=self._tools,
                        resume_claims=_AcceptedResumeClaim(UUID(int=0)),
                    )
                    view = await runtime.start(request)
                await self._projector.project(view)
                await self._controls.settle(lease, runtime_status=view.status)
            await self._session.commit()
            await self._restore_scope(request.scope)
            return view
        except Exception:
            await self._recover_lease(request.scope, lease)
            raise

    async def resume(
        self, *, signal: ResumeSignal, runtime_execution_id: UUID,
    ) -> RuntimeView:
        await self._bound_turn(
            scope=signal.scope,
            turn_id=signal.turn_id,
            runtime_execution_id=runtime_execution_id,
        )
        lease = await self._claim(signal.scope, runtime_execution_id)
        async with scoped_checkpointer(
            self._settings, project_id=signal.scope.project_id,
        ) as saver:
            observer = LangGraphDirectorRuntime(
                checkpointer=saver,
                tools=self._tools,
                resume_claims=_AcceptedResumeClaim(signal.signal_id),
            )
            before = await observer.read(scope=signal.scope, turn_id=signal.turn_id)
        if before.runtime_execution_id != runtime_execution_id:
            await self._recover_lease(signal.scope, lease)
            raise NotFoundError("Director runtime execution not found")
        if before.revision != signal.expected_revision:
            duplicate = (
                before.revision > signal.expected_revision
                and await self._controls.signal_claimed(
                    signal=signal, runtime_execution_id=runtime_execution_id,
                )
            )
            if duplicate:
                await self._projector.project(before)
                await self._controls.settle(lease, runtime_status=before.status)
                await self._session.commit()
                await self._restore_scope(signal.scope)
                return before
            await self._recover_lease(signal.scope, lease)
            raise ConflictError(
                "Director runtime revision changed",
                details={
                    "code": "DIRECTOR_RUNTIME_REVISION_CONFLICT",
                    "revision": before.revision,
                },
            )
        claimed = await self._controls.claim_signal(signal=signal, lease=lease)
        await self._session.commit()
        await self._restore_scope(signal.scope)
        try:
            async with self._controls.guard(lease):
                async with scoped_checkpointer(
                    self._settings, project_id=signal.scope.project_id,
                ) as saver:
                    runtime = LangGraphDirectorRuntime(
                        checkpointer=saver,
                        tools=self._tools,
                        resume_claims=_AcceptedResumeClaim(signal.signal_id),
                    )
                    current = await runtime.read(scope=signal.scope, turn_id=signal.turn_id)
                    if current.runtime_execution_id != runtime_execution_id:
                        raise NotFoundError("Director runtime execution not found")
                    if current.revision < signal.expected_revision:
                        raise ConflictError(
                            "Director runtime signal is ahead of its checkpoint",
                            details={"code": "DIRECTOR_RUNTIME_REVISION_CONFLICT"},
                        )
                    view = (
                        await runtime.resume(signal)
                        if current.revision == signal.expected_revision
                        else current
                    )
                    if not claimed and view.revision == signal.expected_revision:
                        raise ConflictError(
                            "Claimed Director signal has no checkpoint result",
                            details={"code": "DIRECTOR_RESUME_SIGNAL_INCOMPLETE"},
                        )
                await self._projector.project(view)
                await self._controls.settle(lease, runtime_status=view.status)
            await self._session.commit()
            await self._restore_scope(signal.scope)
            return view
        except Exception:
            await self._recover_lease(signal.scope, lease)
            raise

    async def stop(
        self, *, request: StopRequest, runtime_execution_id: UUID,
    ) -> RuntimeView:
        turn = await self._bound_turn(
            scope=request.scope,
            turn_id=request.turn_id,
            runtime_execution_id=runtime_execution_id,
        )
        await self._controls.request_stop(
            project_id=request.scope.project_id,
            runtime_execution_id=runtime_execution_id,
        )
        await self._session.commit()
        await self._restore_scope(request.scope)
        try:
            async with scoped_checkpointer(
                self._settings, project_id=request.scope.project_id,
            ) as saver:
                runtime = LangGraphDirectorRuntime(
                    checkpointer=saver,
                    tools=self._tools,
                    resume_claims=_AcceptedResumeClaim(UUID(int=0)),
                )
                view = await runtime.request_stop(request)
        except NotFoundError as exc:
            # Stop can win the race before the start wakeup writes checkpoint 1.
            # The API atomically cancels the Turn and journals this wakeup, so an
            # absent graph is a completed stop rather than a retryable failure.
            await self._session.rollback()
            await self._restore_scope(request.scope)
            turn = await self._bound_turn(
                scope=request.scope,
                turn_id=request.turn_id,
                runtime_execution_id=runtime_execution_id,
            )
            if turn.status != "cancelled":
                raise
            if turn.engine_version is None or turn.state_schema_version is None:
                raise ConflictError(
                    "Director runtime binding is incomplete",
                    details={"code": "DIRECTOR_ENGINE_BINDING_INVALID"},
                ) from exc
            return RuntimeView(
                turn_id=turn.id,
                runtime_execution_id=runtime_execution_id,
                engine_version=turn.engine_version,
                state_schema_version=turn.state_schema_version,
                revision=request.expected_revision,
                step_count=turn.step_count,
                status="cancelled",
                wait_reason=turn.wait_reason,
                proposal_id=turn.proposal_id,
                dispatched_command_key=turn.dispatched_command_key,
                node_run_ids=tuple(UUID(str(value)) for value in (turn.node_run_ids or [])),
            )
        await self._projector.project(view)
        await self._session.commit()
        await self._restore_scope(request.scope)
        return view

    async def read(
        self, *, scope: RuntimeScope, turn_id: UUID, runtime_execution_id: UUID,
    ) -> RuntimeView:
        await self._bound_turn(
            scope=scope,
            turn_id=turn_id,
            runtime_execution_id=runtime_execution_id,
        )
        async with scoped_checkpointer(self._settings, project_id=scope.project_id) as saver:
            runtime = LangGraphDirectorRuntime(
                checkpointer=saver,
                tools=self._tools,
                resume_claims=_AcceptedResumeClaim(UUID(int=0)),
            )
            view = await runtime.read(scope=scope, turn_id=turn_id)
        if view.runtime_execution_id != runtime_execution_id:
            raise NotFoundError("Director runtime execution not found")
        return view

    async def _claim(self, scope: RuntimeScope, runtime_execution_id: UUID) -> RuntimeLease:
        lease = await self._controls.claim(
            project_id=scope.project_id,
            runtime_execution_id=runtime_execution_id,
            worker_id=self._worker_id,
            ttl=timedelta(minutes=5),
        )
        await self._session.commit()
        await self._restore_scope(scope)
        return lease

    async def _bound_turn(
        self, *, scope: RuntimeScope, turn_id: UUID, runtime_execution_id: UUID,
    ) -> DirectorTurn:
        turn = await DirectorTurnService(self._session).get(
            project_id=scope.project_id, turn_id=turn_id,
        )
        if (
            turn.workspace_id != scope.workspace_id
            or turn.actor_id != scope.actor_id
            or turn.runtime_execution_id != runtime_execution_id
        ):
            raise NotFoundError("Director runtime execution not found")
        return turn

    async def _restore_scope(self, scope: RuntimeScope) -> None:
        await set_rls_context(
            self._session,
            user_id=scope.actor_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
        )

    async def _recover_lease(self, scope: RuntimeScope, lease: RuntimeLease) -> None:
        await self._session.rollback()
        await self._restore_scope(scope)
        try:
            await self._controls.release_waiting(lease)
            await self._session.commit()
            await self._restore_scope(scope)
        except Exception:
            await self._session.rollback()
            await self._restore_scope(scope)


__all__ = ["DirectorRuntimeExecutor"]
