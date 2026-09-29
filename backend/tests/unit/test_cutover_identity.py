"""Frozen V7 identity requires exact target, policy, protocol and handler facts."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.production.cutover_identity import freeze_cutover_execution_identity
from app.production.policy_models import ProductPolicyRevision, ProductPolicyState
from app.production.policy_revisions import ProductPolicyContent
from app.providers.catalog_loader import hash_manifest
from app.providers.handler_registry import ExactHandlerRegistry, RegisteredHandler
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


def _facts(*, dynamic: bool) -> dict[str, Any]:
    workspace_id, connection_id, credential_id, revision_id = (uuid4() for _ in range(4))
    binding = ProviderModelBinding(
        id=uuid4(),
        workspace_id=workspace_id,
        connection_id=connection_id,
        media_type="video",
        model_id="model-v2",
        invoke_model_value="model-v2",
        enabled=True,
    )
    connection = ProviderConnection(
        id=connection_id,
        workspace_id=workspace_id,
        credential_id=credential_id,
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
        base_url="https://example.invalid",
        enabled=True,
    )
    revision = ProviderConnectionRevision(
        id=revision_id,
        connection_id=connection_id,
        credential_revision_id=credential_id,
        provider_type=connection.provider_type,
        protocol_profile=connection.protocol_profile,
        base_url=connection.base_url,
        revision_no=2,
    )
    evidence = ProviderAvailabilityEvidence(
        id=uuid4(),
        workspace_id=workspace_id,
        connection_id=connection_id,
        connection_revision_id=revision_id,
        credential_revision_id=credential_id,
        remote_model_id="model-v2",
        verifier_kind="model_list",
        status="visible",
        listed_model_ids_json=["model-v2"],
    )
    availability = ProviderModelAvailability(
        id=uuid4(),
        workspace_id=workspace_id,
        connection_id=connection_id,
        connection_revision_id=revision_id,
        credential_revision_id=credential_id,
        remote_model_id="model-v2",
        effective_status="visible",
        positive_evidence_id=evidence.id,
        latest_evidence_id=evidence.id,
    )
    contract = {"operation_kind": "video.generate"}
    protocol = ProtocolContractRevision(
        id=uuid4(),
        protocol_contract_id=uuid4(),
        protocol_revision=3,
        protocol_hash=hash_manifest(contract),
        protocol_profile=connection.protocol_profile,
        contract_json=contract,
    )
    global_revision = publication = discovered = capability = None
    if dynamic:
        discovered = ConnectionDiscoveredModel(
            id=uuid4(),
            workspace_id=workspace_id,
            connection_id=connection_id,
            connection_revision_id=revision_id,
            credential_revision_id=credential_id,
            remote_model_id="model-v2",
            protocol_contract_revision_id=protocol.id,
        )
        capability = ConnectionModelCapabilityRevision(
            id=uuid4(),
            workspace_id=workspace_id,
            connection_discovered_model_id=discovered.id,
            capability_revision="r1",
            capability_hash="a" * 64,
            operations_json={},
            input_contracts_json={},
            parameter_constraints_json={},
            evidence_json={},
            implementation_status="contract_tested",
            protocol_contract_revision_id=protocol.id,
        )
        binding.binding_target_kind = "connection_model"
        binding.connection_discovered_model_id = discovered.id
        binding.connection_model_capability_revision_id = capability.id
    else:
        manifest = {"model_id": "model-v2", "model_revision": "r2"}
        global_revision = ModelCapabilityRevision(
            id=uuid4(),
            provider_type=connection.provider_type,
            protocol_profile=connection.protocol_profile,
            canonical_model_id="model-v2",
            model_revision="r2",
            media_kind="video",
            manifest_json=manifest,
            manifest_hash=hash_manifest(manifest),
            source_snapshot_id="source-review",
            implementation_status="contract_tested",
        )
        publication = ModelPublicationState(
            model_capability_revision_id=global_revision.id, lifecycle="active"
        )
        binding.binding_target_kind = "global_model"
        binding.canonical_model_id = "model-v2"
        binding.model_capability_revision_id = global_revision.id

    content = ProductPolicyContent(
        product_path="workbench",
        allowed_operations=frozenset({"video.generate"}),
        allowed_contracts={"video.generate": frozenset({"first_frame"})},
        allowed_options={"video.generate": frozenset({"duration_seconds"})},
    )
    policy = ProductPolicyRevision(
        id=uuid4(),
        policy_id=uuid4(),
        policy_revision=1,
        policy_hash=content.policy_hash(),
        product_path="workbench",
        allowed_operations_json=["video.generate"],
        allowed_contracts_json={"video.generate": ["first_frame"]},
        allowed_options_json={"video.generate": ["duration_seconds"]},
        constraint_overrides_json={},
    )
    state = ProductPolicyState(policy_revision_id=policy.id, status="active")
    handler = RuntimeHandlerRevision(
        id=uuid4(),
        runtime_handler_id=uuid4(),
        handler_revision=1,
        handler_key="minimax-v1",
        implementation_digest="e" * 64,
    )
    registry = ExactHandlerRegistry()
    registry.register(
        RegisteredHandler(
            runtime_handler_id=handler.runtime_handler_id,
            handler_revision=handler.handler_revision,
            handler_key=handler.handler_key,
            implementation_digest=handler.implementation_digest,
            factory=Mock(),
        )
    )
    return {
        "binding": binding,
        "connection": connection,
        "current_connection_revision": revision,
        "latest_connection_revision_no": 2,
        "availability": availability,
        "positive_evidence": evidence,
        "global_revision": global_revision,
        "publication": publication,
        "discovered": discovered,
        "connection_capability": capability,
        "policy": policy,
        "policy_state": state,
        "protocol": protocol,
        "handler": handler,
        "handler_registry": registry,
        "product_path": "workbench",
        "operation": "video.generate",
        "matched_input_contract": "first_frame",
        "resolved_references": [],
        "requested_options": {"duration_seconds": 5},
        "effective_options": {"duration_seconds": 5},
        "transformations": [],
        "request_fingerprint": "f" * 64,
    }


@pytest.mark.parametrize("dynamic", [False, True])
def test_freeze_preserves_only_the_selected_target_identity(dynamic: bool) -> None:
    identity = freeze_cutover_execution_identity(**_facts(dynamic=dynamic))
    assert identity.target.kind == ("connection_model" if dynamic else "global_model")
    assert identity.invoke_model_value == "model-v2"
    assert identity.protocol.protocol_revision == 3
    assert identity.handler.handler_revision == 1


def test_freeze_denies_stale_connection_revoked_policy_and_missing_handler() -> None:
    facts = _facts(dynamic=False)
    facts["latest_connection_revision_no"] = 3
    with pytest.raises(ValueError, match="no longer current"):
        freeze_cutover_execution_identity(**facts)
    facts["latest_connection_revision_no"] = 2
    facts["policy_state"].status = "revoked"
    with pytest.raises(ValueError, match="policy revision is unavailable"):
        freeze_cutover_execution_identity(**facts)
    facts["policy_state"].status = "active"
    facts["handler_registry"] = ExactHandlerRegistry()
    with pytest.raises(LookupError, match="exact runtime handler"):
        freeze_cutover_execution_identity(**facts)


def test_freeze_denies_unlisted_model_and_disallowed_contract() -> None:
    facts = _facts(dynamic=True)
    facts["positive_evidence"].listed_model_ids_json = []
    with pytest.raises(ValueError, match="positive_model_evidence_invalid"):
        freeze_cutover_execution_identity(**facts)
    facts["positive_evidence"].listed_model_ids_json = ["model-v2"]
    facts["matched_input_contract"] = "reference_video"
    with pytest.raises(ValueError, match="product policy denies"):
        freeze_cutover_execution_identity(**facts)
