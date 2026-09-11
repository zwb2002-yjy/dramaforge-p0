"""Database lease, fencing and signal claims for one Director engine execution."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.director_runtime import ResumeSignal
from app.director.runtime.models import DirectorRuntimeControl, DirectorRuntimeSignalClaim
from app.director.turn_models import DirectorTurn
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


class RuntimeLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    turn_id: UUID
    runtime_execution_id: UUID
    worker_id: str = Field(min_length=1, max_length=160)
    epoch: int = Field(ge=1)
    expires_at: datetime


class DirectorRuntimeControlService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bind(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        engine_version: str,
        state_schema_version: str,
    ) -> DirectorRuntimeControl:
        if not engine_version or not state_schema_version:
            raise ValidationAppError("Director engine binding requires exact versions")
        turn = await self._session.scalar(
            select(DirectorTurn).where(
                DirectorTurn.id == turn_id,
                DirectorTurn.project_id == project_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if turn is None:
            raise NotFoundError("Director turn not found")
        if turn.runtime_execution_id is not None:
            row = await self._get(
                project_id=project_id,
                runtime_execution_id=turn.runtime_execution_id,
                lock=True,
            )
            if (
                row.turn_id != turn_id
                or row.engine_version != engine_version
                or row.state_schema_version != state_schema_version
                or turn.engine_version != engine_version
                or turn.state_schema_version != state_schema_version
            ):
                raise ConflictError(
                    "Director turn engine binding is immutable",
                    details={"code": "DIRECTOR_ENGINE_BINDING_CONFLICT"},
                )
            return row
        if turn.engine_version is not None or turn.state_schema_version is not None:
            raise ConflictError(
                "Director turn has an incomplete engine binding",
                details={"code": "DIRECTOR_ENGINE_BINDING_INVALID"},
            )
        execution_id = uuid4()
        turn.engine_version = engine_version
        turn.state_schema_version = state_schema_version
        turn.runtime_execution_id = execution_id
        row = DirectorRuntimeControl(
            runtime_execution_id=execution_id,
            project_id=project_id,
            turn_id=turn_id,
            engine_version=engine_version,
            state_schema_version=state_schema_version,
            status="active",
            revision=1,
            lease_epoch=0,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def claim(
        self,
        *,
        project_id: UUID,
        runtime_execution_id: UUID,
        worker_id: str,
        ttl: timedelta = timedelta(seconds=45),
        now: datetime | None = None,
    ) -> RuntimeLease:
        if (
            not worker_id
            or len(worker_id) > 160
            or ttl <= timedelta(0)
            or ttl > timedelta(minutes=5)
        ):
            raise ValidationAppError("Invalid Director runtime lease request")
        current_time = now or datetime.now(UTC)
        row = await self._get(
            project_id=project_id,
            runtime_execution_id=runtime_execution_id,
            lock=True,
        )
        if row.stop_requested_at is not None or row.status in {
            "stopped", "completed", "failed", "stale",
        }:
            raise ConflictError(
                "Director runtime execution cannot be claimed",
                details={"code": "DIRECTOR_RUNTIME_STOPPED", "status": row.status},
            )
        expires = self._normalized(row.lease_expires_at)
        if row.lease_owner == worker_id and expires is not None and expires > current_time:
            return self._lease(row)
        if row.lease_owner is not None and expires is not None and expires > current_time:
            raise ConflictError(
                "Director runtime execution is leased by another worker",
                details={"code": "DIRECTOR_RUNTIME_LEASE_HELD"},
            )
        row.lease_owner = worker_id
        row.lease_epoch += 1
        row.lease_expires_at = current_time + ttl
        row.status = "active"
        row.revision += 1
        await self._session.flush()
        return self._lease(row)

    @asynccontextmanager
    async def guard(self, lease: RuntimeLease) -> AsyncIterator[DirectorRuntimeControl]:
        """Hold the control-row lock while one checkpoint-changing step runs."""

        row = await self._get(
            project_id=lease.project_id,
            runtime_execution_id=lease.runtime_execution_id,
            lock=True,
        )
        self._assert_lease(row, lease)
        yield row

    async def release_waiting(self, lease: RuntimeLease) -> DirectorRuntimeControl:
        return await self.settle(lease, runtime_status="awaiting_user")

    async def settle(
        self, lease: RuntimeLease, *, runtime_status: str,
    ) -> DirectorRuntimeControl:
        row = await self._get(
            project_id=lease.project_id,
            runtime_execution_id=lease.runtime_execution_id,
            lock=True,
        )
        self._assert_lease(row, lease)
        row.lease_owner = None
        row.lease_expires_at = None
        row.status = {
            "completed": "completed",
            "failed": "failed",
            "cancelled": "stopped",
        }.get(runtime_status, "waiting")
        row.revision += 1
        await self._session.flush()
        return row

    async def request_stop(
        self, *, project_id: UUID, runtime_execution_id: UUID,
    ) -> DirectorRuntimeControl:
        row = await self._get(
            project_id=project_id,
            runtime_execution_id=runtime_execution_id,
            lock=True,
        )
        if row.stop_requested_at is None:
            row.stop_requested_at = datetime.now(UTC)
            row.status = "stopped"
            row.lease_owner = None
            row.lease_expires_at = None
            row.revision += 1
            await self._session.flush()
        return row

    async def mark_project_stale(self, *, project_id: UUID) -> int:
        """Invalidate future graph actions while preserving accepted production facts."""

        changed = await self._session.execute(
            update(DirectorRuntimeControl).where(
                DirectorRuntimeControl.project_id == project_id,
                DirectorRuntimeControl.status.in_(("active", "waiting")),
            ).values(
                status="stale",
                lease_owner=None,
                lease_expires_at=None,
                revision=DirectorRuntimeControl.revision + 1,
            ).returning(DirectorRuntimeControl.runtime_execution_id)
        )
        return len(list(changed.scalars().all()))

    async def claim_signal(self, *, signal: ResumeSignal, lease: RuntimeLease) -> bool:
        if signal.scope.project_id != lease.project_id or signal.turn_id != lease.turn_id:
            raise NotFoundError("Director runtime execution not found")
        row = await self._get(
            project_id=lease.project_id,
            runtime_execution_id=lease.runtime_execution_id,
            lock=True,
        )
        self._assert_lease(row, lease)
        existing = await self._session.scalar(
            select(DirectorRuntimeSignalClaim).where(
                DirectorRuntimeSignalClaim.signal_id == signal.signal_id,
                DirectorRuntimeSignalClaim.project_id == lease.project_id,
                DirectorRuntimeSignalClaim.runtime_execution_id == lease.runtime_execution_id,
            )
        )
        if existing is not None:
            self._require_same_signal(existing, signal)
            return False
        claim = DirectorRuntimeSignalClaim(
            signal_id=signal.signal_id,
            project_id=lease.project_id,
            runtime_execution_id=lease.runtime_execution_id,
            reason=signal.reason,
            reference_id=signal.reference_id,
            expected_revision=signal.expected_revision,
            lease_epoch=lease.epoch,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(claim)
                await self._session.flush()
            return True
        except IntegrityError:
            existing = await self._session.scalar(
                select(DirectorRuntimeSignalClaim).where(
                    DirectorRuntimeSignalClaim.signal_id == signal.signal_id,
                    DirectorRuntimeSignalClaim.project_id == lease.project_id,
                    DirectorRuntimeSignalClaim.runtime_execution_id == lease.runtime_execution_id,
                )
            )
            if existing is None:
                return False
            self._require_same_signal(existing, signal)
            return False

    async def signal_claimed(
        self, *, signal: ResumeSignal, runtime_execution_id: UUID,
    ) -> bool:
        existing = await self._session.scalar(
            select(DirectorRuntimeSignalClaim).where(
                DirectorRuntimeSignalClaim.signal_id == signal.signal_id,
                DirectorRuntimeSignalClaim.project_id == signal.scope.project_id,
                DirectorRuntimeSignalClaim.runtime_execution_id == runtime_execution_id,
            )
        )
        if existing is None:
            return False
        self._require_same_signal(existing, signal)
        return True

    @staticmethod
    def _require_same_signal(
        existing: DirectorRuntimeSignalClaim, signal: ResumeSignal,
    ) -> None:
        if (
            existing.reason != signal.reason
            or existing.reference_id != signal.reference_id
            or existing.expected_revision != signal.expected_revision
        ):
            raise ConflictError(
                "Director resume signal identity was reused",
                details={"code": "DIRECTOR_RESUME_SIGNAL_CONFLICT"},
            ) from None

    async def _get(
        self, *, project_id: UUID, runtime_execution_id: UUID, lock: bool,
    ) -> DirectorRuntimeControl:
        statement = select(DirectorRuntimeControl).where(
            DirectorRuntimeControl.runtime_execution_id == runtime_execution_id,
            DirectorRuntimeControl.project_id == project_id,
        ).execution_options(populate_existing=True)
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise NotFoundError("Director runtime execution not found")
        return row

    @classmethod
    def _assert_lease(cls, row: DirectorRuntimeControl, lease: RuntimeLease) -> None:
        expires = cls._normalized(row.lease_expires_at)
        if (
            row.turn_id != lease.turn_id
            or row.lease_owner != lease.worker_id
            or row.lease_epoch != lease.epoch
            or row.stop_requested_at is not None
            or row.status in {"stopped", "completed", "failed", "stale"}
            or expires is None
            or expires <= datetime.now(UTC)
        ):
            raise ConflictError(
                "Director runtime lease is stale",
                details={"code": "DIRECTOR_RUNTIME_LEASE_STALE"},
            )

    @staticmethod
    def _normalized(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    @staticmethod
    def _lease(row: DirectorRuntimeControl) -> RuntimeLease:
        assert row.lease_owner is not None and row.lease_expires_at is not None
        return RuntimeLease(
            project_id=row.project_id,
            turn_id=row.turn_id,
            runtime_execution_id=row.runtime_execution_id,
            worker_id=row.lease_owner,
            epoch=row.lease_epoch,
            expires_at=row.lease_expires_at,
        )


__all__ = ["DirectorRuntimeControlService", "RuntimeLease"]
