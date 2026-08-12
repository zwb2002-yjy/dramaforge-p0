"""Deterministic Director workflow transition policy."""

from __future__ import annotations

from app.director.enums import ApprovalKind, WorkflowStatus
from app.shared.errors import ValidationAppError

_APPROVAL_TRANSITIONS: dict[tuple[WorkflowStatus, ApprovalKind], WorkflowStatus] = {
    (
        WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION,
        ApprovalKind.CREATIVE_PLAN,
    ): WorkflowStatus.DRAFTING_SHOOTING_PLAN,
    (
        WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION,
        ApprovalKind.SHOOTING_PLAN,
    ): WorkflowStatus.AWAITING_TRIAL_AUTHORIZATION,
    (
        WorkflowStatus.AWAITING_TRIAL_AUTHORIZATION,
        ApprovalKind.TRIAL_BUDGET,
    ): WorkflowStatus.TRIAL_RUNNING,
    (
        WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION,
        ApprovalKind.PRODUCTION_BUDGET,
    ): WorkflowStatus.PRODUCTION_RUNNING,
    (
        WorkflowStatus.AWAITING_REPAIR_AUTHORIZATION,
        ApprovalKind.REPAIR_BUDGET,
    ): WorkflowStatus.PRODUCTION_RUNNING,
}


def status_after_approval(current: WorkflowStatus | str, approval: ApprovalKind) -> WorkflowStatus:
    current_status = WorkflowStatus(current)
    try:
        return _APPROVAL_TRANSITIONS[(current_status, approval)]
    except KeyError as exc:
        raise ValidationAppError(
            f"{approval.value} is not allowed while workflow is {current_status.value}",
            details={
                "code": "DIRECTOR_TRANSITION_NOT_ALLOWED",
                "current_status": current_status.value,
                "approval_kind": approval.value,
            },
        ) from exc


def assert_subjective_override_allowed(*, hard_block: bool) -> None:
    if hard_block:
        raise ValidationAppError(
            "hard quality gates cannot be overridden",
            details={"code": "HARD_GATE_OVERRIDE_FORBIDDEN"},
        )
