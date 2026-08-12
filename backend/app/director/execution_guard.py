"""Fail-closed authorization checks at the paid media execution boundary.

The Director materializer freezes a batch, budget reservation and exact model
binding into every paid ``NodeRun``.  This module validates that immutable
context immediately before a Provider submission.  Projects without a
Director workflow deliberately return ``None`` so the legacy product path is
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import NoReturn
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.director.models import (
    BudgetAuthorization,
    BudgetReservation,
    DirectorWorkflowRun,
    ProductionBatch,
)
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.shared.errors import AppError


@dataclass(frozen=True)
class DirectorMediaExecutionContext:
    workflow_run_id: UUID
    production_batch_id: UUID
    budget_reservation_id: UUID
    budget_authorization_id: UUID
    model_binding_id: UUID | None


async def settle_director_media_cost(
    session: AsyncSession,
    *,
    run: NodeRun,
    operation: ProviderOperation,
) -> None:
    """Idempotently post one Provider cost to the Director budget ledger.

    Providers may report the final amount only after polling.  The marker lives
    on the immutable operation summary so a worker resume cannot charge the
    authorization twice.
    """

    if run.production_batch_id is None or run.budget_reservation_id is None:
        return
    summary = dict(operation.response_summary or {})
    if summary.get("director_budget_settled") is True:
        return
    reservation = await session.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.id == run.budget_reservation_id)
        .with_for_update()
    )
    if reservation is None:
        _reject(
            "DIRECTOR_BUDGET_RESERVATION_INVALID",
            "Director cost cannot be settled because its reservation is missing",
        )
    authorization = await session.scalar(
        select(BudgetAuthorization)
        .where(BudgetAuthorization.id == reservation.authorization_id)
        .with_for_update()
    )
    if authorization is None:
        _reject(
            "DIRECTOR_BUDGET_AUTHORIZATION_INACTIVE",
            "Director cost cannot be settled because its authorization is missing",
        )
    amount = Decimal(str(operation.provider_cost or 0))
    reported_currency = str(operation.currency or reservation.currency).upper()
    ledger_currency = reservation.currency.upper()
    if amount < 0:
        _reject(
            "DIRECTOR_PROVIDER_COST_INVALID",
            "Provider returned a negative cost",
        )
    if amount > 0 and reported_currency != ledger_currency:
        reservation.status = "settlement_error"
        authorization.status = "revoked"
        summary["director_budget_settlement_error"] = "currency_mismatch"
        operation.response_summary = summary
        await session.commit()
        _reject(
            "DIRECTOR_PROVIDER_COST_CURRENCY_MISMATCH",
            "Provider cost currency differs from the authorized budget",
            provider_currency=reported_currency,
            budget_currency=ledger_currency,
        )
    new_reservation_actual = Decimal(str(reservation.actual_amount or 0)) + amount
    new_consumed = Decimal(str(authorization.consumed_amount or 0)) + amount
    reservation.actual_amount = new_reservation_actual
    authorization.consumed_amount = new_consumed
    reservation.settled_at = datetime.now(UTC)
    summary.update(
        {
            "director_budget_settled": True,
            "director_budget_amount": str(amount),
            "director_budget_currency": ledger_currency,
        }
    )
    operation.response_summary = summary
    if new_consumed > authorization.limit_amount:
        reservation.status = "overrun"
        authorization.status = "consumed"
        await session.commit()
        _reject(
            "DIRECTOR_BUDGET_AUTHORIZATION_EXCEEDED",
            "Final Provider cost exceeded the authorized budget",
            consumed_amount=str(new_consumed),
            limit_amount=str(authorization.limit_amount),
        )
    await session.flush()


class DirectorExecutionGuardError(AppError):
    """Stable, worker-visible rejection before any paid Provider POST."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=409, details=details)


def _reject(code: str, message: str, **details: object) -> NoReturn:
    raise DirectorExecutionGuardError(code=code, message=message, details=details)


def _uuid(value: object, *, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        _reject(
            "DIRECTOR_PRODUCTION_CONTEXT_INVALID",
            f"Director media execution has an invalid {field}",
            field=field,
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _expected_authorization_kind(batch_kind: str) -> str:
    expected = {
        "trial": "trial_budget",
        "production": "production_budget",
        "repair": "repair_budget",
    }.get(batch_kind)
    if expected is None:
        _reject(
            "DIRECTOR_PRODUCTION_CONTEXT_INVALID",
            "Director production batch kind is not executable",
            batch_kind=batch_kind,
        )
    return expected


def _frozen_binding_id(
    *,
    snapshot: dict[str, object],
    batch: ProductionBatch,
) -> UUID:
    raw_binding = snapshot.get("model_binding_id")
    binding_id = _uuid(raw_binding, field="model_binding_id")
    purpose = str(snapshot.get("purpose") or "")
    selection = snapshot.get("selection_plan")
    if not purpose or not isinstance(selection, dict):
        _reject(
            "DIRECTOR_MODEL_BINDING_NOT_FROZEN",
            "Director media NodeRun has no frozen selection plan",
        )
    selection_binding_id = _uuid(
        selection.get("model_binding_id"),
        field="selection_plan.model_binding_id",
    )
    if selection_binding_id != binding_id:
        _reject(
            "DIRECTOR_MODEL_BINDING_SNAPSHOT_MISMATCH",
            "Director media NodeRun model binding snapshots disagree",
        )

    plans = (batch.selection_snapshot or {}).get("plans")
    if not isinstance(plans, list):
        _reject(
            "DIRECTOR_MODEL_BINDING_NOT_FROZEN",
            "Director production batch has no frozen selection plans",
        )
    batch_plan = next(
        (
            item
            for item in plans
            if isinstance(item, dict) and item.get("purpose") == purpose
        ),
        None,
    )
    if not isinstance(batch_plan, dict):
        _reject(
            "DIRECTOR_MODEL_BINDING_NOT_FROZEN",
            "Director production batch has no selection for this media purpose",
            purpose=purpose,
        )
    if _uuid(batch_plan.get("model_binding_id"), field="batch.model_binding_id") != binding_id:
        _reject(
            "DIRECTOR_MODEL_BINDING_SNAPSHOT_MISMATCH",
            "Director NodeRun model binding differs from its production batch",
            purpose=purpose,
        )
    return binding_id


def _local_zero_cost_binding(
    *,
    snapshot: dict[str, object],
    batch: ProductionBatch,
) -> bool:
    """Accept an explicitly frozen local, zero-cost TTS plan without a DB binding."""
    if snapshot.get("purpose") != "voice":
        return False
    selection = snapshot.get("selection_plan")
    if not isinstance(selection, dict):
        return False
    if not (
        selection.get("purpose") == "voice"
        and selection.get("provider_type") == "local_tts"
        and selection.get("model_binding_id") is None
    ):
        return False
    plans = (batch.selection_snapshot or {}).get("plans")
    if not isinstance(plans, list):
        return False
    batch_plan = next(
        (
            item
            for item in plans
            if isinstance(item, dict) and item.get("purpose") == "voice"
        ),
        None,
    )
    return bool(
        isinstance(batch_plan, dict)
        and batch_plan.get("provider_type") == "local_tts"
        and batch_plan.get("model_binding_id") is None
        and snapshot.get("model_binding_id") is None
    )


async def validate_director_media_submission(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
    now: datetime | None = None,
) -> DirectorMediaExecutionContext | None:
    """Validate one *new* paid media submission and return its frozen context.

    This must not be used to gate polling/resume of a task already accepted by a
    Provider: an expired authorization must never hide an already-paid result.
    """

    if node.node_type not in {"keyframe", "video", "voice"}:
        return None
    workflow = await session.scalar(
        select(DirectorWorkflowRun).where(DirectorWorkflowRun.project_id == run.project_id)
    )
    if workflow is None:
        return None

    if run.production_batch_id is None or run.budget_reservation_id is None:
        _reject(
            "DIRECTOR_PRODUCTION_CONTEXT_REQUIRED",
            "Director paid media NodeRun requires a production batch and budget reservation",
        )
    batch = await session.get(ProductionBatch, run.production_batch_id)
    reservation = await session.get(BudgetReservation, run.budget_reservation_id)
    if batch is None or reservation is None:
        _reject(
            "DIRECTOR_PRODUCTION_CONTEXT_INVALID",
            "Director production batch or budget reservation no longer exists",
        )

    snapshot = dict(run.input_snapshot or {})
    snapshot_workflow_id = _uuid(snapshot.get("workflow_run_id"), field="workflow_run_id")
    snapshot_batch_id = _uuid(
        snapshot.get("production_batch_id"), field="production_batch_id"
    )
    snapshot_reservation_id = _uuid(
        snapshot.get("budget_reservation_id"), field="budget_reservation_id"
    )
    if (
        batch.project_id != run.project_id
        or batch.workflow_run_id != workflow.id
        or batch.id != snapshot_batch_id
        or workflow.id != snapshot_workflow_id
        or reservation.project_id != run.project_id
        or reservation.batch_id != batch.id
        or reservation.id != snapshot_reservation_id
        or (
            reservation.node_run_id is not None
            and reservation.node_run_id != run.id
        )
    ):
        _reject(
            "DIRECTOR_PRODUCTION_CONTEXT_INVALID",
            "Director media NodeRun authorization lineage does not match",
        )
    if batch.status not in {"authorized", "running"}:
        _reject(
            "DIRECTOR_PRODUCTION_CONTEXT_INVALID",
            "Director production batch is not authorized for execution",
            batch_status=batch.status,
        )
    if reservation.status != "reserved" or reservation.reserved_amount <= Decimal("0"):
        _reject(
            "DIRECTOR_BUDGET_RESERVATION_INVALID",
            "Director budget reservation is not active",
            reservation_status=reservation.status,
        )

    authorization = await session.get(BudgetAuthorization, batch.budget_authorization_id)
    current_time = now or datetime.now(UTC)
    expected_kind = _expected_authorization_kind(batch.batch_kind)
    if (
        authorization is None
        or authorization.id != reservation.authorization_id
        or authorization.project_id != run.project_id
        or authorization.workflow_run_id != workflow.id
        or authorization.authorization_kind != expected_kind
        or authorization.status != "active"
        or _aware(authorization.expires_at) <= current_time
        or authorization.currency.upper() != reservation.currency.upper()
        or reservation.reserved_amount > authorization.limit_amount
    ):
        _reject(
            "DIRECTOR_BUDGET_AUTHORIZATION_INACTIVE",
            "Director budget authorization is invalid, expired, or exceeded",
        )

    total_reserved = await session.scalar(
        select(func.coalesce(func.sum(BudgetReservation.reserved_amount), 0)).where(
            BudgetReservation.authorization_id == authorization.id,
            BudgetReservation.status == "reserved",
        )
    )
    if Decimal(str(total_reserved or 0)) > authorization.limit_amount:
        _reject(
            "DIRECTOR_BUDGET_AUTHORIZATION_EXCEEDED",
            "Director budget authorization has been over-reserved",
        )

    model_binding_id = (
        None
        if _local_zero_cost_binding(snapshot=snapshot, batch=batch)
        else _frozen_binding_id(snapshot=snapshot, batch=batch)
    )
    return DirectorMediaExecutionContext(
        workflow_run_id=workflow.id,
        production_batch_id=batch.id,
        budget_reservation_id=reservation.id,
        budget_authorization_id=authorization.id,
        model_binding_id=model_binding_id,
    )
