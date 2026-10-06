"""Canonical content hash for an immutable connection-scoped capability."""

from __future__ import annotations

from app.providers.catalog_loader import hash_manifest
from app.providers.model_system_models import ConnectionModelCapabilityRevision


def hash_connection_capability(row: ConnectionModelCapabilityRevision) -> str:
    return hash_manifest(
        {
            "connection_discovered_model_id": str(row.connection_discovered_model_id),
            "capability_revision": row.capability_revision,
            "operations": row.operations_json,
            "input_contracts": row.input_contracts_json,
            "parameter_constraints": row.parameter_constraints_json,
            "protocol_contract_revision_id": (
                str(row.protocol_contract_revision_id)
                if row.protocol_contract_revision_id is not None
                else None
            ),
            "evidence": row.evidence_json,
            "implementation_status": row.implementation_status,
        }
    )
