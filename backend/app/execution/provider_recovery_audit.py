"""Read-only inspection of recoverable facts on the single Provider execution chain.

Never calls a Runtime, decrypts credentials, schedules work, polls or commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.execution.models import NodeRun, ProviderOperation
from app.providers.catalog_loader import hash_manifest
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.execution_contract import execution_contract_gaps
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)
from app.providers.runtime import (
    ProviderResumeToken,
    require_operation_identity,
    require_resume_token_identity,
)
from app.security.models import EncryptedProviderCredential
from app.shared.errors import ValidationAppError

RECOVERY_STATES = frozenset(
    {
        "submission_started",
        "submitted",
        "running",
        "timed_out",
        "cancel_requested",
        "unknown_submission",
    }
)


@dataclass(frozen=True)
class ProviderRecoveryAuditRow:
    operation_id: UUID
    node_run_id: UUID
    status: str
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": str(self.operation_id),
            "node_run_id": str(self.node_run_id),
            "status": self.status,
            "identity_preflight_passed": not self.blockers,
            "blockers": list(self.blockers),
            "provider_calls": 0,
            "credential_decryption": "not_performed",
            "remote_state": "not_checked",
        }


async def inspect_provider_operation(
    session: AsyncSession, *, operation: ProviderOperation, run: NodeRun, workspace_id: UUID
) -> ProviderRecoveryAuditRow:
    gaps: list[str] = []
    if operation.node_run_id != run.id:
        gaps.append("EXECUTION_OPERATION_OWNER_MISMATCH")
    if (
        operation.status in {"submission_started", "unknown_submission"}
        and not operation.provider_operation_id
    ):
        gaps.append("PROVIDER_SUBMISSION_UNKNOWN")
    if operation.status == "unknown_submission":
        gaps.append("PROVIDER_SUBMISSION_UNKNOWN")
    if not operation.provider_operation_id:
        gaps.append("REMOTE_IDENTITY_MISSING")
    copies = [
        (operation.selection_plan or {}).get("execution_identity"),
        (operation.request_summary or {}).get("execution_identity"),
        (run.input_snapshot or {}).get("execution_identity"),
    ]
    identity: ExecutionIdentitySnapshot | None = None
    if any(not isinstance(copy, dict) for copy in copies):
        gaps.append("EXECUTION_IDENTITY_MISSING")
    elif copies[0] != copies[1] or copies[0] != copies[2]:
        gaps.append("EXECUTION_IDENTITY_MISMATCH")
    else:
        try:
            identity = ExecutionIdentitySnapshot.model_validate(copies[0])
        except ValueError:
            gaps.append("EXECUTION_IDENTITY_INVALID")
    if identity is not None:
        gaps.extend(execution_contract_gaps(identity.execution_contract))
        try:
            require_operation_identity(identity, operation)
        except ValidationAppError:
            gaps.append("EXECUTION_IDENTITY_MISMATCH")
        if identity.execution_contract is not None and (
            identity.execution_contract.provider_type != operation.actual_provider
            or identity.execution_contract.protocol_profile != operation.protocol_profile
        ):
            gaps.append("EXECUTION_PROTOCOL_MISMATCH")
        connection = await session.get(ProviderConnection, identity.connection_id)
        revision = await session.get(ProviderConnectionRevision, identity.connection_revision_id)
        if connection is None or connection.workspace_id != workspace_id:
            gaps.append("EXECUTION_CONNECTION_OWNER_MISMATCH")
        if revision is None:
            gaps.append("EXECUTION_IDENTITY_REVISION_UNAVAILABLE")
        elif (
            revision.connection_id != identity.connection_id
            or revision.credential_revision_id != identity.credential_revision_id
            or revision.provider_type != operation.actual_provider
            or revision.protocol_profile != operation.protocol_profile
            or revision.auth_mode
            != ("none" if identity.credential_revision_id is None else "bearer")
        ):
            gaps.append("EXECUTION_PROTOCOL_MISMATCH")
        binding = await session.get(ProviderModelBinding, identity.provider_model_binding_id)
        if binding is None or (
            binding.workspace_id != workspace_id
            or binding.connection_id != identity.connection_id
            or binding.catalog_entry_id != identity.catalog_entry_id
            or binding.invoke_model_value != identity.invoke_model_value
        ):
            gaps.append("EXECUTION_IDENTITY_BINDING_UNAVAILABLE")
        entry = await session.get(ModelCatalogEntry, identity.catalog_entry_id)
        if entry is None or (
            entry.model_revision != identity.model_revision
            or entry.contract_manifest_hash != identity.manifest_hash
            or hash_manifest(entry.capability_manifest_json) != identity.manifest_hash
        ):
            gaps.append("EXECUTION_IDENTITY_MODEL_UNAVAILABLE")
        if identity.credential_revision_id is None:
            from app.providers.registry import get_plugin

            try:
                supported = (
                    "none"
                    in get_plugin(
                        operation.actual_provider, operation.protocol_profile or ""
                    ).auth_modes
                )
            except LookupError:
                supported = False
            if revision is None or revision.auth_mode != "none" or not supported:
                gaps.append("EXECUTION_IDENTITY_CREDENTIAL_UNAVAILABLE")
        else:
            credential = (
                await session.execute(
                    select(
                        EncryptedProviderCredential.id, EncryptedProviderCredential.workspace_id
                    ).where(EncryptedProviderCredential.id == identity.credential_revision_id)
                )
            ).first()
            if credential is None or credential.workspace_id != workspace_id:
                gaps.append("EXECUTION_IDENTITY_CREDENTIAL_UNAVAILABLE")
    try:
        resume = ProviderResumeToken.model_validate(operation.resume_token)
    except ValueError:
        gaps.append("RESUME_TOKEN_UNAVAILABLE")
    else:
        try:
            require_resume_token_identity(
                resume,
                remote_task_id=operation.provider_operation_id,
                provider_type=operation.actual_provider,
                protocol_profile=operation.protocol_profile,
                remote_secondary_id=operation.remote_secondary_id,
            )
        except ValidationAppError:
            gaps.append("RESUME_TOKEN_IDENTITY_MISMATCH")
    return ProviderRecoveryAuditRow(
        operation_id=operation.id,
        node_run_id=run.id,
        status=operation.status,
        blockers=tuple(sorted(set(gaps))),
    )


async def audit_provider_recovery(
    session: AsyncSession,
    *,
    workspace_id: UUID | None,
    limit: int = 100,
    after_operation_id: UUID | None = None,
) -> tuple[ProviderRecoveryAuditRow, ...]:
    if not 1 <= limit <= 1000:
        raise ValueError("recovery audit limit must be 1-1000")
    query = (
        select(ProviderOperation, NodeRun, Project.workspace_id)
        .join(NodeRun, ProviderOperation.node_run_id == NodeRun.id)
        .join(Project, NodeRun.project_id == Project.id)
        .where(
            ProviderOperation.execution_path_version == "unified-v1",
            ProviderOperation.status.in_(RECOVERY_STATES),
        )
        .order_by(ProviderOperation.id)
        .limit(limit)
    )
    if workspace_id is not None:
        query = query.where(Project.workspace_id == workspace_id)
    if after_operation_id is not None:
        query = query.where(ProviderOperation.id > after_operation_id)
    results = []
    for operation, run, owner_workspace_id in (await session.execute(query)).all():
        results.append(
            await inspect_provider_operation(
                session, operation=operation, run=run, workspace_id=owner_workspace_id
            )
        )
    return tuple(results)
