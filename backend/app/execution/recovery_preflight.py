"""Read-only exact recovery checks for already submitted V7 Provider operations.

This does not resume, poll, cancel or submit anything. It deliberately ignores
current lifecycle, availability and policy revocation state: those are Create
gates, not conditions for recovering an existing remote task.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.execution.models import NodeRun, ProviderOperation
from app.production.policy_models import ProductPolicyRevision
from app.production.policy_revisions import ProductPolicyContent
from app.providers.catalog_loader import hash_manifest
from app.providers.dynamic_capability_hash import hash_connection_capability
from app.providers.execution_identity import (
    ConnectionModelTargetIdentity,
    CutoverExecutionIdentitySnapshot,
    GlobalModelTargetIdentity,
)
from app.providers.handler_registry import ExactHandlerRegistry
from app.providers.model_system_models import (
    ConnectionDiscoveredModel,
    ConnectionModelCapabilityRevision,
    ModelCapabilityRevision,
    ProtocolContractRevision,
    RuntimeHandlerRevision,
)
from app.providers.models import ProviderConnectionRevision
from app.security.models import EncryptedProviderCredential


@dataclass(frozen=True)
class ExactRecoveryCheck:
    operation_id: UUID
    node_run_id: UUID
    gaps: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.gaps

    def to_json_dict(self) -> dict[str, object]:
        return {
            "operation_id": str(self.operation_id),
            "node_run_id": str(self.node_run_id),
            "ready": self.ready,
            "gaps": list(self.gaps),
        }


def _frozen_identity(
    operation: ProviderOperation, run: NodeRun
) -> CutoverExecutionIdentitySnapshot | None:
    selection = operation.selection_plan if isinstance(operation.selection_plan, dict) else {}
    request = operation.request_summary if isinstance(operation.request_summary, dict) else {}
    snapshot = run.input_snapshot if isinstance(run.input_snapshot, dict) else {}
    copies = [
        selection.get("cutover_execution_identity"),
        request.get("cutover_execution_identity"),
        snapshot.get("cutover_execution_identity"),
    ]
    if (
        any(not isinstance(copy, dict) for copy in copies)
        or copies[0] != copies[1]
        or copies[0] != copies[2]
    ):
        return None
    try:
        return CutoverExecutionIdentitySnapshot.model_validate(copies[0])
    except ValueError:
        return None


async def preflight_recoverable_operation(
    session: AsyncSession,
    *,
    operation: ProviderOperation,
    run: NodeRun,
    workspace_id: UUID,
    handler_registry: ExactHandlerRegistry,
) -> ExactRecoveryCheck:
    """Return only gap labels; every referenced historical revision must exist."""
    if operation.node_run_id is None or operation.node_run_id != run.id:
        raise ValueError("recovery preflight requires the owning NodeRun")
    project = await session.get(Project, run.project_id)
    if project is None or project.workspace_id != workspace_id:
        return ExactRecoveryCheck(operation.id, run.id, ("operation_workspace_mismatch",))
    gaps: list[str] = []
    if operation.status not in {
        "created",
        "submission_started",
        "submitted",
        "running",
        "cancel_requested",
        "unknown_submission",
        "timed_out",
    }:
        gaps.append("operation_not_recoverable")
    if operation.status == "unknown_submission":
        gaps.append("unknown_submission_requires_manual_reconciliation")
    remote_required = operation.status in {"submitted", "running", "cancel_requested"}
    if remote_required and operation.provider_operation_id is None:
        gaps.append("remote_operation_id_missing")
    if (
        remote_required or operation.provider_operation_id is not None
    ) and not operation.resume_token:
        gaps.append("resume_token_missing")
    if (
        operation.status in {"submission_started", "timed_out"}
        and operation.provider_operation_id is None
    ):
        gaps.append("submission_outcome_unconfirmed")
    identity = _frozen_identity(operation, run)
    if identity is None:
        gaps.append("exact_execution_identity_missing_or_mismatched")
        return ExactRecoveryCheck(operation.id, run.id, tuple(gaps))
    revision = await session.get(ProviderConnectionRevision, identity.connection_revision_id)
    if (
        revision is None
        or revision.connection_id != identity.connection_id
        or revision.credential_revision_id != identity.credential_revision_id
        or operation.connection_id != identity.connection_id
        or operation.provider_connection_revision_id != identity.connection_revision_id
        or operation.credential_revision_id != identity.credential_revision_id
        or operation.model_binding_id != identity.binding_id
        or operation.actual_model != identity.invoke_model_value
        or operation.operation_kind != identity.operation
        or operation.request_fingerprint != identity.request_fingerprint
        or operation.actual_provider != revision.provider_type
        or operation.protocol_profile != revision.protocol_profile
    ):
        gaps.append("operation_or_connection_revision_mismatch")
    if operation.resume_token:
        from app.providers.runtime import ProviderResumeToken

        try:
            token = ProviderResumeToken.model_validate(operation.resume_token)
        except ValueError:
            gaps.append("resume_token_invalid")
        else:
            if (
                token.provider_type != operation.actual_provider
                or token.protocol_profile != operation.protocol_profile
                or token.remote_task_id != operation.provider_operation_id
                or token.remote_secondary_id != operation.remote_secondary_id
            ):
                gaps.append("resume_token_identity_mismatch")
    credential = await session.get(EncryptedProviderCredential, identity.credential_revision_id)
    if credential is None or credential.workspace_id != workspace_id:
        gaps.append("historical_credential_revision_missing")
    policy = await session.get(ProductPolicyRevision, identity.policy.product_policy_revision_id)
    if (
        policy is None
        or policy.policy_id != identity.policy.product_policy_id
        or policy.policy_revision != identity.policy.policy_revision
        or policy.policy_hash != identity.policy.policy_hash
    ):
        gaps.append("historical_policy_revision_mismatch")
    else:
        try:
            policy_content = ProductPolicyContent(
                product_path=policy.product_path,
                allowed_operations=frozenset(policy.allowed_operations_json),
                allowed_contracts={
                    key: frozenset(value) for key, value in policy.allowed_contracts_json.items()
                },
                allowed_options={
                    key: frozenset(value) for key, value in policy.allowed_options_json.items()
                },
                constraint_overrides=policy.constraint_overrides_json,
            )
            if policy_content.policy_hash() != policy.policy_hash:
                gaps.append("historical_policy_revision_mismatch")
        except (AttributeError, TypeError, ValueError):
            gaps.append("historical_policy_revision_mismatch")
    protocol = await session.get(
        ProtocolContractRevision, identity.protocol.protocol_contract_revision_id
    )
    if (
        protocol is None
        or protocol.protocol_contract_id != identity.protocol.protocol_contract_id
        or protocol.protocol_revision != identity.protocol.protocol_revision
        or protocol.protocol_hash != identity.protocol.protocol_hash
        or protocol.protocol_hash != hash_manifest(protocol.contract_json)
        or protocol.contract_json.get("operation_kind") != identity.operation
        or (revision is not None and protocol.protocol_profile != revision.protocol_profile)
    ):
        gaps.append("historical_protocol_revision_mismatch")
    handler = await session.get(
        RuntimeHandlerRevision, identity.handler.runtime_handler_revision_id
    )
    if (
        handler is None
        or handler.runtime_handler_id != identity.handler.runtime_handler_id
        or handler.handler_revision != identity.handler.handler_revision
        or handler.implementation_digest != identity.handler.implementation_digest
    ):
        gaps.append("historical_handler_revision_mismatch")
    else:
        try:
            handler_registry.resolve_for_operation(
                handler,
                protocol_profile=protocol.protocol_profile if protocol is not None else "",
                operation_kind=identity.operation,
            )
        except LookupError:
            gaps.append("exact_historical_handler_unavailable")
    if isinstance(identity.target, GlobalModelTargetIdentity):
        model = await session.get(
            ModelCapabilityRevision, identity.target.model_capability_revision_id
        )
        if (
            model is None
            or model.canonical_model_id != identity.target.canonical_model_id
            or model.model_revision != identity.target.model_revision
            or model.manifest_hash != identity.target.manifest_hash
            or model.manifest_hash != hash_manifest(model.manifest_json)
            or (revision is not None and model.provider_type != revision.provider_type)
            or (revision is not None and model.protocol_profile != revision.protocol_profile)
        ):
            gaps.append("historical_global_model_revision_mismatch")
    elif isinstance(identity.target, ConnectionModelTargetIdentity):
        discovered = await session.get(
            ConnectionDiscoveredModel, identity.target.connection_discovered_model_id
        )
        capability = await session.get(
            ConnectionModelCapabilityRevision,
            identity.target.connection_model_capability_revision_id,
        )
        if (
            discovered is None
            or capability is None
            or discovered.workspace_id != workspace_id
            or capability.workspace_id != workspace_id
            or discovered.connection_id != identity.connection_id
            or discovered.connection_revision_id != identity.connection_revision_id
            or discovered.credential_revision_id != identity.credential_revision_id
            or discovered.remote_model_id != identity.target.remote_model_id
            or discovered.protocol_contract_revision_id
            != identity.protocol.protocol_contract_revision_id
            or capability.connection_discovered_model_id != discovered.id
            or capability.protocol_contract_revision_id
            != identity.protocol.protocol_contract_revision_id
            or capability.capability_hash != identity.target.connection_capability_hash
            or capability.capability_hash != hash_connection_capability(capability)
        ):
            gaps.append("historical_connection_model_revision_mismatch")
    return ExactRecoveryCheck(operation.id, run.id, tuple(gaps))
