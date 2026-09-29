"""Read-only target and availability gate for the single Binding entity.

This is not the complete Provider Create gate: ProductPolicy, technical matching,
frozen protocol/handler resolution and Dispatch still need to be composed around
this result before the runtime can switch from legacy eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.catalog_loader import hash_manifest
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


@dataclass(frozen=True)
class TargetEligibility:
    target_kind: str
    eligible: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def evaluate_cutover_binding_target(
    *,
    binding: ProviderModelBinding,
    connection: ProviderConnection,
    current_connection_revision: ProviderConnectionRevision,
    availability: ProviderModelAvailability | None,
    new_binding: bool,
    global_revision: ModelCapabilityRevision | None = None,
    publication: ModelPublicationState | None = None,
    discovered: ConnectionDiscoveredModel | None = None,
    connection_capability: ConnectionModelCapabilityRevision | None = None,
    protocol: ProtocolContractRevision | None = None,
) -> TargetEligibility:
    """Evaluate one target from an exact, already loaded connection snapshot.

    The caller must select the highest connection revision and recheck it at the
    eventual Create boundary. This read-only result does not authorize a submit.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    if not binding.enabled:
        blockers.append("binding_disabled")
    if not connection.enabled:
        blockers.append("connection_disabled")
    if binding.workspace_id != connection.workspace_id or binding.connection_id != connection.id:
        blockers.append("binding_connection_mismatch")
    if (
        current_connection_revision.connection_id != connection.id
        or current_connection_revision.credential_revision_id != connection.credential_id
        or current_connection_revision.provider_type != connection.provider_type
        or current_connection_revision.protocol_profile != connection.protocol_profile
        or current_connection_revision.base_url != connection.base_url
    ):
        blockers.append("connection_revision_stale")
    if not binding.invoke_model_value:
        blockers.append("invoke_model_value_missing")
    if (
        availability is None
        or availability.workspace_id != binding.workspace_id
        or availability.connection_id != connection.id
        or availability.connection_revision_id != current_connection_revision.id
        or availability.credential_revision_id != current_connection_revision.credential_revision_id
        or availability.remote_model_id != binding.invoke_model_value
        or availability.effective_status != "visible"
        or availability.positive_evidence_id is None
    ):
        blockers.append("current_model_not_visible")

    target_kind = binding.binding_target_kind or "unresolved"
    if target_kind == "global_model":
        if (
            global_revision is None
            or binding.model_capability_revision_id != global_revision.id
            or binding.canonical_model_id != global_revision.canonical_model_id
            or binding.model_id != global_revision.canonical_model_id
            or global_revision.provider_type != connection.provider_type
            or global_revision.protocol_profile != connection.protocol_profile
            or global_revision.media_kind != binding.media_type
            or global_revision.manifest_hash != hash_manifest(global_revision.manifest_json)
            or not global_revision.source_snapshot_id
            or global_revision.implementation_status != "contract_tested"
        ):
            blockers.append("global_capability_not_ready")
        if (
            publication is None
            or global_revision is None
            or publication.model_capability_revision_id != global_revision.id
        ):
            blockers.append("global_publication_missing")
        elif publication.lifecycle == "deprecated" and not new_binding:
            warnings.append("global_model_deprecated")
        elif publication.lifecycle not in ({"active"} if new_binding else {"active", "legacy"}):
            blockers.append("global_lifecycle_denies_target")
        if (
            binding.connection_discovered_model_id
            or binding.connection_model_capability_revision_id
        ):
            blockers.append("mixed_binding_target")
    elif target_kind == "connection_model":
        if binding.model_capability_revision_id or binding.canonical_model_id:
            blockers.append("mixed_binding_target")
        if (
            discovered is None
            or binding.connection_discovered_model_id != discovered.id
            or discovered.workspace_id != binding.workspace_id
            or discovered.connection_id != connection.id
            or discovered.connection_revision_id != current_connection_revision.id
            or discovered.credential_revision_id
            != current_connection_revision.credential_revision_id
            or discovered.remote_model_id != binding.invoke_model_value
        ):
            blockers.append("connection_discovery_stale_or_missing")
        if (
            connection_capability is None
            or discovered is None
            or binding.connection_model_capability_revision_id != connection_capability.id
            or connection_capability.workspace_id != binding.workspace_id
            or connection_capability.connection_discovered_model_id != discovered.id
            or connection_capability.implementation_status != "contract_tested"
        ):
            blockers.append("connection_capability_not_tested")
        if (
            protocol is None
            or discovered is None
            or connection_capability is None
            or discovered.protocol_contract_revision_id != protocol.id
            or connection_capability.protocol_contract_revision_id != protocol.id
            or protocol.protocol_profile != connection.protocol_profile
            or protocol.protocol_hash != hash_manifest(protocol.contract_json)
        ):
            blockers.append("protocol_contract_unmapped")
    else:
        blockers.append("binding_target_unresolved")

    return TargetEligibility(
        target_kind=target_kind,
        eligible=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )
