"""Revision-safe lifecycle and recovery for durable Director turns.

This service coordinates Director decisions only. It never invokes a model,
creates a media NodeRun, or promotes an Artifact to Formal.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project, User
from app.director.turn_models import DirectorTurn
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

ACTIVE_TURN_STATUSES = frozenset(
    {"queued", "thinking", "awaiting_user", "awaiting_execution"}
)
TERMINAL_TURN_STATUSES = frozenset({"completed", "failed", "cancelled", "stale"})
DEFAULT_TURN_MAX_STEPS = 4
MAX_TURN_STEPS = 8
DEFAULT_TURN_DEADLINE = timedelta(hours=24)

_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"thinking", "failed", "cancelled", "stale"}),
    "thinking": frozenset(
        {"awaiting_user", "awaiting_execution", "completed", "failed", "cancelled", "stale"}
    ),
    "awaiting_user": frozenset({"awaiting_execution", "completed", "failed", "cancelled", "stale"}),
    "awaiting_execution": frozenset(
        {"awaiting_user", "completed", "failed", "cancelled", "stale"}
    ),
}

_PATCH_FIELDS = frozenset(
    {
        "model_resolution",
        "transport_record_id",
        "transport_status",
        "request_summary",
        "response_summary",
        "token_usage",
        "provider_cost",
        "cost_status",
        "currency",
        "output_hash",
        "output_snapshot",
        "wait_reason",
        "proposal_id",
        "dispatched_command_key",
        "node_run_ids",
        "schema_repair_count",
        "last_error",
    }
)


def _context_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bounded(value: str | None, limit: int = 2000) -> str | None:
    return value[:limit] if value else None


def _deadline_passed(deadline: datetime | None, now: datetime) -> bool:
    if deadline is None:
        return False
    normalized_deadline = deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=UTC)
    normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return normalized_deadline <= normalized_now


class DirectorTurnService:
    """Own legal transitions, optimistic revisions, and safe recovery."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get(
        self,
        *,
        project: Project,
        actor: User,
        scope_type: str,
        scope_entity_id: UUID,
        request_key: str,
        context_snapshot: Mapping[str, object],
        input_versions: Mapping[str, object] | None = None,
        intent_snapshot: Mapping[str, object] | None = None,
        max_steps: int = DEFAULT_TURN_MAX_STEPS,
        deadline: datetime | None = None,
    ) -> tuple[DirectorTurn, bool]:
        key = request_key.strip()
        if not key or len(key) > 200:
            raise ValidationAppError(
                "Director request_key must contain 1 to 200 characters",
                details={"code": "DIRECTOR_REQUEST_KEY_INVALID"},
            )
        if not scope_type.strip() or len(scope_type) > 24:
            raise ValidationAppError(
                "Director scope_type is invalid",
                details={"code": "DIRECTOR_SCOPE_INVALID"},
            )
        if max_steps < 1 or max_steps > MAX_TURN_STEPS:
            raise ValidationAppError(
                f"Director max_steps must be between 1 and {MAX_TURN_STEPS}",
                details={"code": "DIRECTOR_STEP_LIMIT_INVALID"},
            )
        fingerprint = _context_hash(context_snapshot)
        await self.assert_context_not_rejected(project_id=project.id, context_hash=fingerprint)
        existing = await self._by_request_key(project_id=project.id, request_key=key)
        if existing is not None:
            self._require_same_context(existing, fingerprint)
            return existing, False

        turn = DirectorTurn(
            workspace_id=project.workspace_id,
            project_id=project.id,
            actor_id=actor.id,
            scope_type=scope_type.strip(),
            scope_entity_id=scope_entity_id,
            request_key=key,
            context_hash=fingerprint,
            input_versions=dict(input_versions or {}),
            intent_snapshot=dict(intent_snapshot or {}),
            request_summary={"max_steps": max_steps},
            status="queued",
            wait_reason="director_worker",
            step_count=0,
            deadline=deadline or datetime.now(UTC) + DEFAULT_TURN_DEADLINE,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(turn)
                await self._session.flush()
        except IntegrityError:
            existing = await self._by_request_key(project_id=project.id, request_key=key)
            if existing is None:
                raise
            self._require_same_context(existing, fingerprint)
            return existing, False
        return turn, True

    async def get(self, *, project_id: UUID, turn_id: UUID) -> DirectorTurn:
        turn = await self._session.scalar(
            select(DirectorTurn).where(
                DirectorTurn.id == turn_id,
                DirectorTurn.project_id == project_id,
            )
        )
        if turn is None:
            raise NotFoundError("Director turn not found")
        return turn

    async def list(
        self,
        *,
        project_id: UUID,
        scope_type: str | None = None,
        scope_entity_id: UUID | None = None,
        limit: int = 50,
    ) -> list[DirectorTurn]:
        stmt = select(DirectorTurn).where(DirectorTurn.project_id == project_id)
        if scope_type is not None:
            stmt = stmt.where(DirectorTurn.scope_type == scope_type)
        if scope_entity_id is not None:
            stmt = stmt.where(DirectorTurn.scope_entity_id == scope_entity_id)
        rows = await self._session.execute(
            stmt.order_by(DirectorTurn.created_at.desc(), DirectorTurn.id.desc()).limit(limit)
        )
        return list(rows.scalars().all())

    async def claim(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        expected_revision: int,
        now: datetime | None = None,
    ) -> DirectorTurn:
        ts = now or datetime.now(UTC)
        current = await self.get(project_id=project_id, turn_id=turn_id)
        max_steps = self._max_steps(current)
        claimed = await self._session.scalar(
            update(DirectorTurn)
            .execution_options(synchronize_session=False)
            .where(
                DirectorTurn.id == turn_id,
                DirectorTurn.project_id == project_id,
                DirectorTurn.status == "queued",
                DirectorTurn.revision == expected_revision,
                DirectorTurn.step_count < max_steps,
                or_(DirectorTurn.deadline.is_(None), DirectorTurn.deadline > ts),
            )
            .values(
                status="thinking",
                wait_reason="director_analysis",
                step_count=DirectorTurn.step_count + 1,
                revision=DirectorTurn.revision + 1,
                last_error=None,
            )
            .returning(DirectorTurn.id)
        )
        if claimed is None:
            await self._session.refresh(current)
            if _deadline_passed(current.deadline, ts):
                await self._fail_limit(current, reason="deadline_exceeded")
            elif current.step_count >= max_steps:
                await self._fail_limit(current, reason="step_limit_reached")
            else:
                raise ConflictError(
                    "Director turn could not be claimed",
                    details={
                        "code": "DIRECTOR_TURN_CLAIM_CONFLICT",
                        "status": current.status,
                        "revision": current.revision,
                    },
                )
            raise ConflictError(
                "Director turn reached its bounded stop condition",
                details={
                    "code": "DIRECTOR_TURN_LIMIT_REACHED",
                    "status": current.status,
                    "wait_reason": current.wait_reason,
                },
            )
        await self._session.refresh(current)
        return current

    async def compare_and_set(
        self,
        *,
        turn: DirectorTurn,
        expected_statuses: Sequence[str],
        target_status: str,
        updates: Mapping[str, object] | None = None,
        increment_step: bool = False,
        now: datetime | None = None,
    ) -> DirectorTurn:
        if target_status != turn.status and target_status not in _TRANSITIONS.get(
            turn.status, frozenset()
        ):
            raise ValidationAppError(
                f"illegal Director turn transition {turn.status} -> {target_status}",
                details={"code": "DIRECTOR_TURN_TRANSITION_INVALID"},
            )
        patch = dict(updates or {})
        unsupported = sorted(set(patch) - _PATCH_FIELDS)
        if unsupported:
            raise ValidationAppError(
                f"unsupported Director turn patch field: {unsupported[0]}",
                details={"code": "DIRECTOR_TURN_PATCH_INVALID"},
            )
        if "last_error" in patch:
            patch["last_error"] = _bounded(
                str(patch["last_error"]) if patch["last_error"] is not None else None
            )
        ts = now or datetime.now(UTC)
        if increment_step:
            await self.enforce_limits(turn, now=ts)
        expected_revision = turn.revision
        statement = update(DirectorTurn).where(
            DirectorTurn.id == turn.id,
            DirectorTurn.project_id == turn.project_id,
            DirectorTurn.revision == expected_revision,
            DirectorTurn.status.in_(tuple(expected_statuses)),
        )
        values: dict[str, object] = {
            **patch,
            "status": target_status,
            "revision": DirectorTurn.revision + 1,
        }
        if increment_step:
            statement = statement.where(
                DirectorTurn.step_count < self._max_steps(turn),
                or_(DirectorTurn.deadline.is_(None), DirectorTurn.deadline > ts),
            )
            values["step_count"] = DirectorTurn.step_count + 1
        changed = await self._session.scalar(
            statement.values(**values).returning(DirectorTurn.id)
            .execution_options(synchronize_session=False)
        )
        if changed is None:
            await self._session.refresh(turn)
            raise ConflictError(
                "Director turn changed concurrently",
                details={
                    "code": "DIRECTOR_TURN_REVISION_CONFLICT",
                    "status": turn.status,
                    "revision": turn.revision,
                },
            )
        await self._session.refresh(turn)
        return turn

    async def stop(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        expected_revision: int,
    ) -> DirectorTurn:
        turn = await self.get(project_id=project_id, turn_id=turn_id)
        if turn.revision != expected_revision:
            raise ConflictError(
                "Director turn revision conflict",
                details={
                    "code": "DIRECTOR_TURN_REVISION_CONFLICT",
                    "status": turn.status,
                    "revision": turn.revision,
                },
            )
        if turn.status in TERMINAL_TURN_STATUSES:
            return turn
        return await self.compare_and_set(
            turn=turn,
            expected_statuses=tuple(ACTIVE_TURN_STATUSES),
            target_status="cancelled",
            updates={
                "wait_reason": "user_stopped",
                "last_error": "New Director actions stopped by user; in-flight media is unchanged.",
            },
        )

    async def assert_context_not_rejected(self, *, project_id: UUID, context_hash: str) -> None:
        rejected = await self._session.scalar(
            select(DirectorTurn.id).where(
                DirectorTurn.project_id == project_id,
                DirectorTurn.context_hash == context_hash,
                DirectorTurn.status == "completed",
                or_(
                    DirectorTurn.response_summary["user_decision"]["decision"].as_string()
                    == "reject",
                    DirectorTurn.wait_reason == "proposal_rejected",
                ),
            ).limit(1)
        )
        if rejected is not None:
            raise ConflictError(
                "This unchanged suggestion context was already rejected by the user",
                details={"code": "DIRECTOR_CONTEXT_REJECTED", "turn_id": str(rejected)},
            )

    async def record_user_decision(
        self, *, project_id: UUID, turn_id: UUID, expected_revision: int,
        decision: str, accepted_operation_indices: Sequence[int],
    ) -> DirectorTurn:
        """Record a detached Shot suggestion decision, never apply its content."""
        turn = await self.get(project_id=project_id, turn_id=turn_id)
        task = (turn.request_summary or {}).get("task")
        if (
            turn.proposal_id is not None or turn.node_run_ids or turn.dispatched_command_key
            or task not in {"shot_director_suggestion", "shot_director_recommendation"}
        ):
            raise ValidationAppError(
                "Use the canonical Proposal decision API for linked or unsupported suggestions",
                details={"code": "DIRECTOR_DECISION_UNSUPPORTED"},
            )
        output = turn.output_snapshot or {}
        if task == "shot_director_suggestion":
            count = 1 if "suggested_director_state" in output else 0
        else:
            operations = output.get("typed_operations")
            count = len(operations) if isinstance(operations, list) else 0
        indices = list(accepted_operation_indices)
        if (
            decision not in {"accept", "reject"}
            or any(type(index) is not int or index < 0 or index >= count for index in indices)
            or len(indices) != len(set(indices))
            or (decision == "accept" and not indices)
            or (decision == "reject" and indices)
            or not turn.output_hash
        ):
            raise ValidationAppError(
                "Decision must name only accepted operations from the persisted suggestion",
                details={"code": "DIRECTOR_DECISION_INVALID"},
            )
        audit: dict[str, object] = {
            "decision": decision,
            "accepted_operation_indices": sorted(indices),
            "rejected_operation_indices": [index for index in range(count) if index not in indices],
            "output_hash": turn.output_hash,
        }
        summary = dict(turn.response_summary or {})
        previous = summary.get("user_decision")
        if previous is not None:
            if previous == audit:
                return turn
            raise ConflictError(
                "This suggestion already has a different explicit decision",
                details={"code": "DIRECTOR_DECISION_CONFLICT"},
            )
        if turn.status != "awaiting_user" or turn.revision != expected_revision:
            raise ConflictError(
                "Director decision checkpoint changed",
                details={"code": "DIRECTOR_TURN_REVISION_CONFLICT", "revision": turn.revision},
            )
        if decision == "accept":
            from app.assets.models import Shot

            shot = await self._session.scalar(
                select(Shot).where(
                    Shot.id == turn.scope_entity_id, Shot.project_id == project_id,
                ).with_for_update().execution_options(populate_existing=True)
            )
            expected_shot = (turn.input_versions or {}).get("shot")
            if (
                turn.scope_type != "shot" or shot is None
                or expected_shot != shot.version
                or output.get("base_shot_version") != shot.version
            ):
                raise ConflictError(
                    "Shot changed since this suggestion was produced",
                    details={"code": "DIRECTOR_DECISION_STALE"},
                )
        summary["user_decision"] = audit
        try:
            turn = await self.compare_and_set(
                turn=turn, expected_statuses=("awaiting_user",),
                target_status="completed" if decision == "reject" else "awaiting_user",
                updates={
                    "response_summary": summary,
                    "wait_reason": "user_rejected" if decision == "reject" else "design_save",
                },
                increment_step=decision == "accept",
            )
        except ConflictError:
            await self._session.refresh(turn)
            if (turn.response_summary or {}).get("user_decision") == audit:
                return turn
            raise
        if decision == "reject":
            # Close already-in-flight sibling requests for the same business
            # context. Their paid transport, if submitted, is not cancelled.
            await self._session.execute(
                update(DirectorTurn).where(
                    DirectorTurn.project_id == project_id,
                    DirectorTurn.context_hash == turn.context_hash,
                    DirectorTurn.id != turn.id,
                    DirectorTurn.status.in_(tuple(ACTIVE_TURN_STATUSES)),
                ).values(
                    status="stale", wait_reason="context_rejected",
                    last_error="The user rejected this unchanged suggestion context.",
                    revision=DirectorTurn.revision + 1,
                )
            )
        return turn

    async def mark_project_stale(self, *, project_id: UUID, reason: str) -> int:
        changed = await self._session.execute(
            update(DirectorTurn).where(
                DirectorTurn.project_id == project_id,
                DirectorTurn.status.in_(tuple(ACTIVE_TURN_STATUSES)),
            ).values(
                status="stale", wait_reason="autonomy_changed", last_error=_bounded(reason),
                revision=DirectorTurn.revision + 1,
            ).returning(DirectorTurn.id)
        )
        return len(list(changed.scalars().all()))

    async def mark_scope_stale(
        self,
        *,
        project_id: UUID,
        scope_type: str,
        scope_entity_id: UUID,
        reason: str,
    ) -> int:
        result = await self._session.execute(
            update(DirectorTurn)
            .where(
                DirectorTurn.project_id == project_id,
                DirectorTurn.scope_type == scope_type,
                DirectorTurn.scope_entity_id == scope_entity_id,
                DirectorTurn.status.in_(tuple(ACTIVE_TURN_STATUSES)),
            )
            .values(
                status="stale",
                wait_reason="context_changed",
                last_error=_bounded(reason),
                revision=DirectorTurn.revision + 1,
            )
            .returning(DirectorTurn.id)
        )
        return len(list(result.scalars().all()))

    async def recover_interrupted(
        self,
        *,
        project_id: UUID,
        turn_id: UUID,
        now: datetime | None = None,
    ) -> DirectorTurn:
        """Recover by reading durable facts only; never resubmit text/media."""

        ts = now or datetime.now(UTC)
        turn = await self.get(project_id=project_id, turn_id=turn_id)
        if turn.status in TERMINAL_TURN_STATUSES:
            return turn
        if _deadline_passed(turn.deadline, ts):
            await self._fail_limit(turn, reason="deadline_exceeded")
            return turn
        if turn.step_count >= self._max_steps(turn):
            await self._fail_limit(turn, reason="step_limit_reached")
            return turn
        if turn.status == "thinking" and turn.transport_status == "submission_started":
            return await self.compare_and_set(
                turn=turn,
                expected_statuses=("thinking",),
                target_status="failed",
                updates={
                    "transport_status": "unknown_submission",
                    "wait_reason": "text_submission_unknown",
                    "last_error": (
                        "Interrupted text submission has no pollable remote identity; "
                        "automatic replay is forbidden. Start an explicit new request."
                    ),
                },
            )
        return turn

    async def enforce_limits(
        self, turn: DirectorTurn, *, now: datetime | None = None, advancing: bool = True
    ) -> None:
        """Fail stopped turns durably in the caller transaction, even on replay."""
        reason = (
            "deadline_exceeded"
            if _deadline_passed(turn.deadline, now or datetime.now(UTC))
            else "step_limit_reached"
            if advancing and turn.step_count >= self._max_steps(turn)
            else None
        )
        if reason is not None:
            await self._fail_limit(turn, reason=reason)
            raise ConflictError(
                "Director turn reached its finite limit",
                details={"code": "DIRECTOR_TURN_LIMIT_REACHED", "wait_reason": reason},
            )

    async def _fail_limit(self, turn: DirectorTurn, *, reason: str) -> None:
        if turn.status not in ACTIVE_TURN_STATUSES:
            return
        await self.compare_and_set(
            turn=turn,
            expected_statuses=tuple(ACTIVE_TURN_STATUSES),
            target_status="failed",
            updates={
                "wait_reason": reason,
                "last_error": f"Director turn stopped: {reason}.",
            },
        )

    async def _by_request_key(
        self,
        *,
        project_id: UUID,
        request_key: str,
    ) -> DirectorTurn | None:
        turn: DirectorTurn | None = await self._session.scalar(
            select(DirectorTurn).where(
                DirectorTurn.project_id == project_id,
                DirectorTurn.request_key == request_key,
            )
        )
        return turn

    @staticmethod
    def _require_same_context(turn: DirectorTurn, context_hash: str) -> None:
        if turn.context_hash != context_hash:
            raise ConflictError(
                "Director request key was already used for different context",
                details={"code": "DIRECTOR_REQUEST_KEY_REUSED", "turn_id": str(turn.id)},
            )

    @staticmethod
    def _max_steps(turn: DirectorTurn) -> int:
        raw = (turn.request_summary or {}).get("max_steps")
        if isinstance(raw, int) and 1 <= raw <= MAX_TURN_STEPS:
            return raw
        return DEFAULT_TURN_MAX_STEPS


__all__ = [
    "ACTIVE_TURN_STATUSES",
    "DEFAULT_TURN_DEADLINE",
    "DEFAULT_TURN_MAX_STEPS",
    "DirectorTurnService",
    "MAX_TURN_STEPS",
    "TERMINAL_TURN_STATUSES",
]
