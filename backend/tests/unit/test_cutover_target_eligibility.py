"""Global and connection-scoped targets use distinct evidence gates."""

from __future__ import annotations

from uuid import uuid4

from app.providers.catalog_loader import hash_manifest
from app.providers.cutover_target_eligibility import evaluate_cutover_binding_target
from app.providers.model_system_models import (
    ConnectionDiscoveredModel,
    ConnectionModelCapabilityRevision,
    ModelCapabilityRevision,
    ModelPublicationState,
    ProtocolContractRevision,
    ProviderModelAvailability,
)
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)


def _common() -> tuple[
    ProviderModelBinding,
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelAvailability,
]:
    workspace_id, connection_id, credential_id, revision_id = (uuid4() for _ in range(4))
    binding = ProviderModelBinding(
        id=uuid4(),
        workspace_id=workspace_id,
        connection_id=connection_id,
        media_type="video",
        model_id="MiniMax-H3",
        invoke_model_value="MiniMax-H3",
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
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
        base_url="https://example.invalid",
    )
    availability = ProviderModelAvailability(
        id=uuid4(),
        workspace_id=workspace_id,
        connection_id=connection_id,
        connection_revision_id=revision_id,
        credential_revision_id=credential_id,
        remote_model_id="MiniMax-H3",
        effective_status="visible",
        positive_evidence_id=uuid4(),
        latest_evidence_id=uuid4(),
    )
    return binding, connection, revision, availability


def test_global_lifecycle_and_exact_visibility_matrix() -> None:
    binding, connection, revision, availability = _common()
    manifest = {"model_id": "MiniMax-H3", "model_revision": "v2"}
    model = ModelCapabilityRevision(
        id=uuid4(),
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
        canonical_model_id="MiniMax-H3",
        model_revision="v2",
        media_kind="video",
        manifest_json=manifest,
        manifest_hash=hash_manifest(manifest),
        source_snapshot_id="reviewed-source",
        implementation_status="contract_tested",
    )
    binding.binding_target_kind = "global_model"
    binding.canonical_model_id = "MiniMax-H3"
    binding.model_capability_revision_id = model.id
    publication = ModelPublicationState(model_capability_revision_id=model.id, lifecycle="active")

    def evaluate(*, new_binding: bool = False):
        return evaluate_cutover_binding_target(
            binding=binding,
            connection=connection,
            current_connection_revision=revision,
            availability=availability,
            new_binding=new_binding,
            global_revision=model,
            publication=publication,
        )

    assert evaluate(new_binding=True).eligible
    publication.lifecycle = "legacy"
    assert evaluate().eligible
    assert "global_lifecycle_denies_target" in evaluate(new_binding=True).blockers
    publication.lifecycle = "deprecated"
    assert evaluate().eligible
    assert evaluate().warnings == ("global_model_deprecated",)
    assert "global_lifecycle_denies_target" in evaluate(new_binding=True).blockers
    publication.lifecycle = "retired"
    assert "global_lifecycle_denies_target" in evaluate().blockers
    publication.lifecycle = "active"
    availability.effective_status = "not_checked"
    assert "current_model_not_visible" in evaluate().blockers
    availability.effective_status = "visible"
    availability.connection_revision_id = uuid4()
    assert "current_model_not_visible" in evaluate().blockers
    availability.connection_revision_id = revision.id
    revision.credential_revision_id = uuid4()
    assert "connection_revision_stale" in evaluate().blockers
    assert "current_model_not_visible" in evaluate().blockers


def test_dynamic_target_uses_current_discovery_without_global_lifecycle() -> None:
    binding, connection, revision, availability = _common()
    discovered = ConnectionDiscoveredModel(
        id=uuid4(),
        workspace_id=binding.workspace_id,
        connection_id=connection.id,
        connection_revision_id=revision.id,
        credential_revision_id=revision.credential_revision_id,
        remote_model_id=binding.invoke_model_value,
    )
    contract = {"operation": "video.generate"}
    protocol = ProtocolContractRevision(
        id=uuid4(),
        protocol_contract_id=uuid4(),
        protocol_revision=1,
        protocol_hash=hash_manifest(contract),
        protocol_profile=connection.protocol_profile,
        contract_json=contract,
    )
    capability = ConnectionModelCapabilityRevision(
        id=uuid4(),
        workspace_id=binding.workspace_id,
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
    discovered.protocol_contract_revision_id = protocol.id
    binding.binding_target_kind = "connection_model"
    binding.connection_discovered_model_id = discovered.id
    binding.connection_model_capability_revision_id = capability.id

    def evaluate():
        return evaluate_cutover_binding_target(
            binding=binding,
            connection=connection,
            current_connection_revision=revision,
            availability=availability,
            new_binding=True,
            discovered=discovered,
            connection_capability=capability,
            protocol=protocol,
        )

    assert evaluate().eligible
    discovered.connection_revision_id = uuid4()
    assert "connection_discovery_stale_or_missing" in evaluate().blockers
    discovered.connection_revision_id = revision.id
    capability.implementation_status = "manifest_mapped"
    assert "connection_capability_not_tested" in evaluate().blockers
    capability.implementation_status = "contract_tested"
    protocol.protocol_hash = "b" * 64
    assert "protocol_contract_unmapped" in evaluate().blockers
