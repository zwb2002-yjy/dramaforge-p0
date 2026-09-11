"""Durable scheduling records for independent Director runtime steps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.director_runtime import ResumeSignal, RuntimeInput, StopRequest
from app.director.runtime.executor import DirectorRuntimeExecutor
from app.director.runtime.models import DirectorRuntimeWakeup
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError

RuntimeWakeupKind = Literal["start", "resume", "stop", "recovery"]


class ClaimedRuntimeWakeup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    project_id: UUID
    runtime_execution_id: UUID
    turn_id: UUID
    kind: RuntimeWakeupKind
    payload: dict[str, object]
    attempt_count: int
    owner_user_id: UUID
    workspace_id: UUID


class RuntimeExecutorFactory(Protocol):
    def __call__(
        self, session: AsyncSession, wakeup: ClaimedRuntimeWakeup,
    ) -> DirectorRuntimeExecutor: ...


class DirectorRuntimeWakeupService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_start(self, request: RuntimeInput) -> DirectorRuntimeWakeup:
        return await self._enqueue(
            project_id=request.scope.project_id,
            runtime_execution_id=request.runtime_execution_id,
            kind="start",
            dedupe_key=f"start:{request.runtime_execution_id}",
            payload=request.model_dump(mode="json"),
        )

    async def enqueue_resume(
        self, signal: ResumeSignal, *, runtime_execution_id: UUID,
    ) -> DirectorRuntimeWakeup:
        return await self._enqueue(
            project_id=signal.scope.project_id,
            runtime_execution_id=runtime_execution_id,
            kind="resume",
            dedupe_key=f"resume:{runtime_execution_id}:{signal.signal_id}",
            payload=signal.model_dump(mode="json"),
        )

    async def enqueue_stop(
        self, request: StopRequest, *, runtime_execution_id: UUID,
    ) -> DirectorRuntimeWakeup:
        return await self._enqueue(
            project_id=request.scope.project_id,
            runtime_execution_id=runtime_execution_id,
            kind="stop",
            dedupe_key=f"stop:{request.request_id}",
            payload=request.model_dump(mode="json"),
        )

    async def _enqueue(
        self,
        *,
        project_id: UUID,
        runtime_execution_id: UUID,
        kind: RuntimeWakeupKind,
        dedupe_key: str,
        payload: dict[str, object],
    ) -> DirectorRuntimeWakeup:
        existing = await self._by_key(project_id=project_id, dedupe_key=dedupe_key)
        if existing is not None:
            self._require_same(existing, kind, runtime_execution_id, payload)
            return existing
        row = DirectorRuntimeWakeup(
            project_id=project_id,
            runtime_execution_id=runtime_execution_id,
            kind=kind,
            dedupe_key=dedupe_key,
            payload=payload,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
            return row
        except IntegrityError:
            existing = await self._by_key(project_id=project_id, dedupe_key=dedupe_key)
            if existing is None:
                raise
            self._require_same(existing, kind, runtime_execution_id, payload)
            return existing

    async def _by_key(
        self, *, project_id: UUID, dedupe_key: str,
    ) -> DirectorRuntimeWakeup | None:
        return cast(
            DirectorRuntimeWakeup | None,
            await self._session.scalar(select(DirectorRuntimeWakeup).where(
                DirectorRuntimeWakeup.project_id == project_id,
                DirectorRuntimeWakeup.dedupe_key == dedupe_key,
            )),
        )

    @staticmethod
    def _require_same(
        row: DirectorRuntimeWakeup,
        kind: RuntimeWakeupKind,
        runtime_execution_id: UUID,
        payload: dict[str, object],
    ) -> None:
        if (
            row.kind != kind
            or row.runtime_execution_id != runtime_execution_id
            or row.payload != payload
        ):
            raise ConflictError(
                "Director runtime wakeup key was reused",
                details={"code": "DIRECTOR_RUNTIME_WAKEUP_CONFLICT"},
            )


async def claim_runtime_wakeup(
    factory: async_sessionmaker[AsyncSession], *, wakeup_id: UUID,
) -> ClaimedRuntimeWakeup | None:
    async with factory() as session:
        result = await session.execute(
            text("SELECT * FROM app.pending_director_runtime_wakeups(:wakeup_id)"),
            {"wakeup_id": wakeup_id},
        )
        scope = result.mappings().one_or_none()
        if scope is None:
            return None
        await set_rls_context(
            session,
            user_id=scope["owner_user_id"],
            workspace_id=scope["workspace_id"],
            project_id=scope["project_id"],
        )
        row = await session.scalar(
            select(DirectorRuntimeWakeup).where(
                DirectorRuntimeWakeup.id == wakeup_id,
                DirectorRuntimeWakeup.completed_at.is_(None),
                DirectorRuntimeWakeup.dead_letter_at.is_(None),
                DirectorRuntimeWakeup.next_attempt_at <= datetime.now(UTC),
            ).with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        if row.attempt_count >= 5:
            row.dead_letter_at = datetime.now(UTC)
            row.last_error = "RuntimeWakeupAttemptsExhausted"
            await session.commit()
            return None
        row.attempt_count += 1
        row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.commit()
        return ClaimedRuntimeWakeup(
            id=row.id,
            project_id=row.project_id,
            runtime_execution_id=row.runtime_execution_id,
            turn_id=scope["turn_id"],
            kind=row.kind,  # type: ignore[arg-type]
            payload=dict(row.payload),
            attempt_count=row.attempt_count,
            owner_user_id=scope["owner_user_id"],
            workspace_id=scope["workspace_id"],
        )


async def finish_runtime_wakeup(
    factory: async_sessionmaker[AsyncSession],
    *,
    wakeup: ClaimedRuntimeWakeup,
    error: Exception | None,
) -> None:
    async with factory() as session:
        await set_rls_context(
            session,
            user_id=wakeup.owner_user_id,
            workspace_id=wakeup.workspace_id,
            project_id=wakeup.project_id,
        )
        row = await session.scalar(
            select(DirectorRuntimeWakeup).where(
                DirectorRuntimeWakeup.id == wakeup.id,
                DirectorRuntimeWakeup.attempt_count == wakeup.attempt_count,
                DirectorRuntimeWakeup.completed_at.is_(None),
                DirectorRuntimeWakeup.dead_letter_at.is_(None),
            ).with_for_update()
        )
        if row is None:
            return
        now = datetime.now(UTC)
        if error is None:
            row.completed_at = now
            row.last_error = None
        else:
            row.last_error = type(error).__name__[:120]
            if row.attempt_count >= 5:
                row.dead_letter_at = now
            else:
                row.next_attempt_at = now + timedelta(
                    seconds=min(300, 5 * 2**row.attempt_count),
                )
        await session.commit()


async def process_runtime_wakeup(
    factory: async_sessionmaker[AsyncSession],
    *,
    wakeup_id: UUID,
    executor_factory: RuntimeExecutorFactory,
) -> bool:
    wakeup = await claim_runtime_wakeup(factory, wakeup_id=wakeup_id)
    if wakeup is None:
        return False
    error: Exception | None = None
    try:
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=wakeup.owner_user_id,
                workspace_id=wakeup.workspace_id,
                project_id=wakeup.project_id,
            )
            executor = executor_factory(session, wakeup)
            if wakeup.kind in {"start", "recovery"}:
                await executor.start(RuntimeInput.model_validate(wakeup.payload))
            elif wakeup.kind == "resume":
                await executor.resume(
                    signal=ResumeSignal.model_validate(wakeup.payload),
                    runtime_execution_id=wakeup.runtime_execution_id,
                )
            else:
                await executor.stop(
                    request=StopRequest.model_validate(wakeup.payload),
                    runtime_execution_id=wakeup.runtime_execution_id,
                )
    except ConflictError as exc:
        # A user stop, mode change, or stale binding is a successful no-op for
        # an older durable wakeup. Retrying it cannot produce useful work.
        if exc.details.get("code") != "DIRECTOR_RUNTIME_STOPPED":
            error = exc
    except Exception as exc:  # noqa: BLE001 - durable retry records the class only
        error = exc
    await finish_runtime_wakeup(factory, wakeup=wakeup, error=error)
    return error is None


__all__ = [
    "ClaimedRuntimeWakeup",
    "DirectorRuntimeWakeupService",
    "RuntimeWakeupKind",
    "claim_runtime_wakeup",
    "finish_runtime_wakeup",
    "process_runtime_wakeup",
]
