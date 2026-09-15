"""Invocation journal operations; callers own commit and network ordering."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.director.invocation_models import DirectorInvocation
from app.director.turn_models import DirectorTurn
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


class InvocationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def prepare(
        self, *, project_id: UUID, turn_id: UUID, invocation_key: str, step_key: str,
        attempt: int, model_resolution: dict[str, object], request_snapshot: dict[str, object],
        output_schema: dict[str, object], intent_version: str,
    ) -> DirectorInvocation:
        if (not invocation_key or len(invocation_key) > 200 or not step_key
                or len(step_key) > 160 or attempt < 1 or not intent_version
                or len(intent_version) > 100):
            raise ValidationAppError("Invalid invocation identity")
        # Serialize preparation on the scoped parent, including concurrent first
        # inserts. Never accept a caller's ORM turn as scope authority.
        turn = await self._session.scalar(select(DirectorTurn).where(
            DirectorTurn.id == turn_id, DirectorTurn.project_id == project_id,
        ).with_for_update().execution_options(populate_existing=True))
        if turn is None:
            raise NotFoundError("Director turn not found")
        fingerprint = _hash({
            "step_key": step_key, "attempt": attempt, "model_resolution": model_resolution,
            "request": request_snapshot, "schema": output_schema, "intent_version": intent_version,
        })
        existing = await self._session.scalar(select(DirectorInvocation).where(
            DirectorInvocation.turn_id == turn_id, DirectorInvocation.project_id == project_id,
            DirectorInvocation.invocation_key == invocation_key,
        ).execution_options(populate_existing=True))
        if existing is not None:
            if existing.input_hash != fingerprint:
                raise ConflictError("Invocation identity was reused with different input")
            return existing
        row = DirectorInvocation(
            project_id=project_id, turn_id=turn_id, invocation_key=invocation_key,
            step_key=step_key, attempt=attempt, input_hash=fingerprint,
            model_resolution=model_resolution, request_snapshot=request_snapshot,
            output_schema=output_schema, intent_version=intent_version,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, *, project_id: UUID, invocation_id: UUID) -> DirectorInvocation:
        row = await self._session.scalar(select(DirectorInvocation).where(
            DirectorInvocation.id == invocation_id, DirectorInvocation.project_id == project_id,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise NotFoundError("Director invocation not found")
        return row

    async def list_for_turn(
        self, *, project_id: UUID, turn_id: UUID,
    ) -> list[DirectorInvocation]:
        """Return the durable call history in execution order for recovery."""

        rows = await self._session.scalars(
            select(DirectorInvocation).where(
                DirectorInvocation.project_id == project_id,
                DirectorInvocation.turn_id == turn_id,
            ).order_by(DirectorInvocation.created_at, DirectorInvocation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(rows)

    async def start(self, *, project_id: UUID, invocation_id: UUID) -> bool:
        """Reserve submission once. Caller MUST commit before any model request.

        False never authorizes resubmission, even if a previous response is lost.
        """
        row = await self.get(project_id=project_id, invocation_id=invocation_id)
        if row.status != "prepared":
            return False
        row.status = "submission_started"
        row.submission_started_at = datetime.now(UTC)
        await self._session.flush()
        return True

    async def complete(
        self, *, project_id: UUID, invocation_id: UUID, output: BaseModel,
        token_usage: dict[str, object], reported_cost: Decimal | None = None,
    ) -> DirectorInvocation:
        row = await self.get(project_id=project_id, invocation_id=invocation_id)
        if type(output).model_json_schema(mode="validation") != row.output_schema:
            raise ConflictError("Invocation output schema changed")
        # Revalidate even model_construct() values rather than trusting the caller.
        validated = type(output).model_validate(output.model_dump()).model_dump(mode="json")
        output_hash = _hash(validated)
        if row.status == "completed":
            if (row.output_hash != output_hash or row.token_usage != token_usage
                    or row.reported_cost != reported_cost):
                raise ConflictError("Completed invocation evidence cannot be replaced")
            return row
        if row.status not in {"submission_started", "unknown_submission"}:
            raise ConflictError("Invocation is not awaiting a response")
        if reported_cost is not None and (not reported_cost.is_finite() or reported_cost < 0):
            raise ValidationAppError("Invalid reported invocation cost")
        row.validated_output = validated
        row.output_hash = output_hash
        row.token_usage = token_usage
        row.reported_cost = reported_cost
        row.cost_status = "unknown" if reported_cost is None else "reported"
        row.status = "completed"
        row.error_code = None
        row.finished_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def mark_unknown(self, *, project_id: UUID, invocation_id: UUID) -> None:
        row = await self.get(project_id=project_id, invocation_id=invocation_id)
        if row.status == "unknown_submission":
            return
        if row.status != "submission_started":
            raise ConflictError("Only submitted invocations can have an unknown response")
        row.status = "unknown_submission"
        row.error_code = "SUBMISSION_OUTCOME_UNKNOWN"
        await self._session.flush()

    async def record_failure(
        self, *, project_id: UUID, invocation_id: UUID, error_code: str,
    ) -> None:
        row = await self.get(project_id=project_id, invocation_id=invocation_id)
        if row.status == "failed" and row.error_code == error_code:
            return
        if row.status != "submission_started":
            raise ConflictError("Invocation cannot be marked failed from its current state")
        row.status = "failed"
        row.error_code = error_code[:120]
        row.finished_at = datetime.now(UTC)
        await self._session.flush()
