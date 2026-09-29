"""Build the exact V7 identity from already selected, immutable model facts.

This is an offline composition seam. The current Dispatch/Worker path does not
call it yet; wiring it requires the matching Create and recovery gates.
"""

from __future__ import annotations

from pydantic import JsonValue

from app.production.policy_models import ProductPolicyRevision, ProductPolicyState
from app.production.policy_revisions import ProductPolicyContent
from app.providers.catalog_loader import hash_manifest
from app.providers.cutover_target_eligibility import evaluate_cutover_binding_target
from app.providers.execution_identity import (
    ConnectionModelTargetIdentity,
    CutoverExecutionIdentitySnapshot,
    ExecutionIdentityReference,
    GlobalModelTargetIdentity,
    HandlerRevisionIdentity,
    PolicyRevisionIdentity,
    ProtocolRevisionIdentity,
)
from app.providers.handler_registry import ExactHandlerRegistry
from app.providers.model_system_models import (
    ConnectionDiscoveredModel,
    ConnectionModelCapabilityRevision,
    ModelCapabilityRevision,
    ModelPublicationState,
    ProtocolContractRevision,
    ProviderAvailabilityEvidence,
    ProviderModelAvailability,
    RuntimeHandlerRevision,
)
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)


def freeze_cutover_execution_identity(
    *,
    binding: ProviderModelBinding,
    connection: ProviderConnection,
    current_connection_revision: ProviderConnectionRevision,
    latest_connection_revision_no: int,
    availability: ProviderModelAvailability | None,
    positive_evidence: ProviderAvailabilityEvidence | None,
    global_revision: ModelCapabilityRevision | None,
    publication: ModelPublicationState | None,
    discovered: ConnectionDiscoveredModel | None,
    connection_capability: ConnectionModelCapabilityRevision | None,
    policy: ProductPolicyRevision,
    policy_state: ProductPolicyState,
    protocol: ProtocolContractRevision,
    handler: RuntimeHandlerRevision,
    handler_registry: ExactHandlerRegistry,
    product_path: str,
    operation: str,
    matched_input_contract: str,
    resolved_references: list[ExecutionIdentityReference],
    requested_options: dict[str, JsonValue],
    effective_options: dict[str, JsonValue],
    transformations: list[dict[str, JsonValue]],
    request_fingerprint: str,
    new_binding: bool = False,
) -> CutoverExecutionIdentitySnapshot:
    """Freeze selected facts or fail closed before a Provider Create.

    The caller must load and lock the latest connection revision and provide its
    revision number. A future Dispatch caller must persist this result before
    allowing the worker to submit. No network operation occurs here.
    """
    if current_connection_revision.revision_no != latest_connection_revision_no:
        raise ValueError("connection revision is no longer current")
    eligibility = evaluate_cutover_binding_target(
        binding=binding,
        connection=connection,
        current_connection_revision=current_connection_revision,
        availability=availability,
        positive_evidence=positive_evidence,
        new_binding=new_binding,
        global_revision=global_revision,
        publication=publication,
        discovered=discovered,
        connection_capability=connection_capability,
        protocol=protocol,
    )
    if not eligibility.eligible:
        raise ValueError(f"binding target is not eligible: {', '.join(eligibility.blockers)}")
    if (
        policy_state.policy_revision_id != policy.id
        or policy_state.status != "active"
        or policy.product_path != product_path
    ):
        raise ValueError("product policy revision is unavailable")
    content = ProductPolicyContent(
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
    if content.policy_hash() != policy.policy_hash:
        raise ValueError("product policy revision hash does not match its content")
    if (
        operation not in content.allowed_operations
        or matched_input_contract not in content.allowed_contracts.get(operation, frozenset())
        or not {key for key, value in requested_options.items() if value is not None}
        <= content.allowed_options.get(operation, frozenset())
    ):
        raise ValueError("product policy denies the selected request")
    if (
        protocol.protocol_profile != connection.protocol_profile
        or protocol.protocol_hash != hash_manifest(protocol.contract_json)
        or protocol.contract_json.get("operation_kind") != operation
    ):
        raise ValueError("protocol revision does not match the selected operation")
    # A stored revision without a deployed implementation is not a runnable
    # handler. Registry resolution checks exact ID, revision, key and digest.
    handler_registry.resolve(handler)

    target: GlobalModelTargetIdentity | ConnectionModelTargetIdentity
    if eligibility.target_kind == "global_model":
        assert global_revision is not None
        target = GlobalModelTargetIdentity(
            model_capability_revision_id=global_revision.id,
            canonical_model_id=global_revision.canonical_model_id,
            model_revision=global_revision.model_revision,
            manifest_hash=global_revision.manifest_hash,
        )
    else:
        assert discovered is not None and connection_capability is not None
        target = ConnectionModelTargetIdentity(
            connection_discovered_model_id=discovered.id,
            connection_model_capability_revision_id=connection_capability.id,
            connection_capability_hash=connection_capability.capability_hash,
            remote_model_id=discovered.remote_model_id,
        )
    assert binding.invoke_model_value is not None
    return CutoverExecutionIdentitySnapshot(
        binding_id=binding.id,
        target=target,
        invoke_model_value=binding.invoke_model_value,
        policy=PolicyRevisionIdentity(
            product_policy_revision_id=policy.id,
            product_policy_id=policy.policy_id,
            policy_revision=policy.policy_revision,
            policy_hash=policy.policy_hash,
        ),
        protocol=ProtocolRevisionIdentity(
            protocol_contract_revision_id=protocol.id,
            protocol_contract_id=protocol.protocol_contract_id,
            protocol_revision=protocol.protocol_revision,
            protocol_hash=protocol.protocol_hash,
        ),
        handler=HandlerRevisionIdentity(
            runtime_handler_revision_id=handler.id,
            runtime_handler_id=handler.runtime_handler_id,
            handler_revision=handler.handler_revision,
            implementation_digest=handler.implementation_digest,
        ),
        connection_id=connection.id,
        connection_revision_id=current_connection_revision.id,
        credential_revision_id=current_connection_revision.credential_revision_id,
        operation=operation,
        matched_input_contract=matched_input_contract,
        resolved_references=resolved_references,
        requested_options=requested_options,
        effective_options=effective_options,
        transformations=transformations,
        request_fingerprint=request_fingerprint,
    )
