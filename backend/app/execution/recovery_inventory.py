"""Read-only early inventory of operations that may need historical recovery.

This reports candidate mapping and missing frozen facts. It is not the exact
handler preflight required before runtime cutover.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.execution.models import NodeRun, ProviderOperation

_ACTIVE_STATUSES = frozenset(
    {"created", "submission_started", "submitted", "running", "cancel_requested"}
)
_RECONCILIATION_STATUSES = frozenset({"unknown_submission", "timed_out"})


@dataclass(frozen=True)
class RecoveryInventoryRow:
    operation_id: UUID
    node_run_id: UUID
    status: str
    operation_kind: str
    actual_provider: str
    protocol_profile: str | None
    execution_path_version: str | None
    has_remote_operation_id: bool
    has_resume_token: bool
    has_execution_identity: bool
    connection_revision_id: UUID | None
    credential_revision_id: UUID | None
    model_binding_id: UUID | None
    candidate_handler: str | None
    gaps: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        result = asdict(self)
        for key in (
            "operation_id",
            "node_run_id",
            "connection_revision_id",
            "credential_revision_id",
            "model_binding_id",
        ):
            value = result[key]
            result[key] = str(value) if value is not None else None
        return result


@dataclass(frozen=True)
class RecoveryInventoryReport:
    workspace_id: UUID
    rows: tuple[RecoveryInventoryRow, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "workspace_id": str(self.workspace_id),
            "candidate_count": len(self.rows),
            "operations_with_gaps": sum(bool(row.gaps) for row in self.rows),
            "exact_gate_ready": False,
            "operations": [row.to_json_dict() for row in self.rows],
        }


def classify_recovery_candidate(operation: ProviderOperation) -> RecoveryInventoryRow:
    """Classify one persisted operation without exposing request or resume data."""
    selection = operation.selection_plan if isinstance(operation.selection_plan, dict) else {}
    request = operation.request_summary if isinstance(operation.request_summary, dict) else {}
    identity = selection.get("execution_identity") or request.get("execution_identity")
    has_identity = isinstance(identity, dict)
    gaps: list[str] = []
    if operation.provider_connection_revision_id is None:
        gaps.append("connection_revision_missing")
    if operation.credential_revision_id is None:
        gaps.append("credential_revision_missing")
    if operation.model_binding_id is None:
        gaps.append("model_binding_missing")
    if not has_identity:
        gaps.append("frozen_execution_identity_missing")
    if operation.protocol_profile is None:
        gaps.append("protocol_profile_missing")
    # A concrete handler revision does not exist in the pre-cutover schema.
    gaps.append("exact_handler_revision_not_mapped")
    if operation.provider_operation_id is not None and operation.resume_token is None:
        gaps.append("resume_token_missing")
    if operation.status == "unknown_submission":
        gaps.append("unknown_submission_requires_manual_reconciliation")
    candidate = (
        f"{operation.actual_provider}/{operation.protocol_profile}/"
        f"{operation.execution_path_version or 'unknown_path'}"
        if operation.protocol_profile is not None
        else None
    )
    if operation.node_run_id is None:
        raise ValueError("recovery inventory requires a NodeRun ownership chain")
    return RecoveryInventoryRow(
        operation_id=operation.id,
        node_run_id=operation.node_run_id,
        status=operation.status,
        operation_kind=operation.operation_kind,
        actual_provider=operation.actual_provider,
        protocol_profile=operation.protocol_profile,
        execution_path_version=operation.execution_path_version,
        has_remote_operation_id=operation.provider_operation_id is not None,
        has_resume_token=operation.resume_token is not None,
        has_execution_identity=has_identity,
        connection_revision_id=operation.provider_connection_revision_id,
        credential_revision_id=operation.credential_revision_id,
        model_binding_id=operation.model_binding_id,
        candidate_handler=candidate,
        gaps=tuple(gaps),
    )


async def build_recovery_inventory(
    session: AsyncSession, *, workspace_id: UUID
) -> RecoveryInventoryReport:
    """Inspect RLS-visible operations for one Owner workspace; make no writes."""
    operations = list(
        (
            await session.scalars(
                select(ProviderOperation)
                .join(NodeRun, ProviderOperation.node_run_id == NodeRun.id)
                .join(Project, NodeRun.project_id == Project.id)
                .where(
                    Project.workspace_id == workspace_id,
                    ProviderOperation.status.in_(
                        _ACTIVE_STATUSES | _RECONCILIATION_STATUSES
                    ),
                )
                .order_by(ProviderOperation.created_at, ProviderOperation.id)
            )
        ).all()
    )
    return RecoveryInventoryReport(
        workspace_id=workspace_id,
        rows=tuple(classify_recovery_candidate(item) for item in operations),
    )
