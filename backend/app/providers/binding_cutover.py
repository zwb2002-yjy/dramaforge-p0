"""Read-only classification of the existing ProviderModelBinding identities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.catalog_loader import hash_manifest
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.model_system_models import (
    ConnectionDiscoveredModel,
    ConnectionModelCapabilityRevision,
    ModelCapabilityRevision,
    ModelPublicationState,
    ProviderModelAvailability,
)
from app.providers.models import (
    ProviderConnection,
    ProviderConnectionRevision,
    ProviderModelBinding,
)

BindingTargetKind = Literal["global_model", "connection_model", "unresolved"]


@dataclass(frozen=True)
class BindingCutoverRow:
    binding_id: UUID
    enabled: bool
    connection_id: UUID
    purpose: str
    model_id: str
    invoke_model_value: str | None
    target_kind: BindingTargetKind
    model_capability_revision_id: UUID | None
    connection_discovered_model_id: UUID | None
    connection_model_capability_revision_id: UUID | None
    availability: str
    classification_evidence: dict[str, str | None]
    blocking_reasons: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        values = asdict(self)
        for name in (
            "binding_id",
            "connection_id",
            "model_capability_revision_id",
            "connection_discovered_model_id",
            "connection_model_capability_revision_id",
        ):
            value = values[name]
            values[name] = str(value) if value is not None else None
        return values


@dataclass(frozen=True)
class BindingCutoverReport:
    workspace_id: UUID
    rows: tuple[BindingCutoverRow, ...]

    @property
    def enabled_unresolved_count(self) -> int:
        return sum(row.enabled and row.target_kind == "unresolved" for row in self.rows)

    @property
    def enabled_blocked_count(self) -> int:
        return sum(row.enabled and bool(row.blocking_reasons) for row in self.rows)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "workspace_id": str(self.workspace_id),
            "enabled_unresolved_count": self.enabled_unresolved_count,
            "enabled_blocked_count": self.enabled_blocked_count,
            "bindings": [row.to_json_dict() for row in self.rows],
        }


async def build_binding_cutover_report(
    session: AsyncSession, *, workspace_id: UUID
) -> BindingCutoverReport:
    """Audit one RLS-scoped Workspace without changing bindings or evidence."""
    bindings = list(
        (
            await session.scalars(
                select(ProviderModelBinding)
                .where(ProviderModelBinding.workspace_id == workspace_id)
                .order_by(ProviderModelBinding.id)
            )
        ).all()
    )
    rows: list[BindingCutoverRow] = []
    for binding in bindings:
        blockers: list[str] = []
        evidence: dict[str, str | None] = {
            "legacy_catalog_entry_id": (
                str(binding.catalog_entry_id) if binding.catalog_entry_id is not None else None
            ),
            "legacy_manifest_hash": binding.capability_manifest_hash,
            "global_manifest_hash": None,
            "model_revision": None,
            "remote_resource_kind": binding.remote_resource_kind,
            "remote_resource_id": binding.remote_resource_id,
            "source_snapshot_id": None,
            "connection_revision_id": None,
            "credential_revision_id": None,
            "availability_evidence_id": None,
            "positive_availability_evidence_id": None,
        }
        connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.id == binding.connection_id,
                ProviderConnection.workspace_id == workspace_id,
            )
        )
        revision: ProviderConnectionRevision | None = None
        if connection is None:
            blockers.append("connection_missing")
        else:
            if not connection.enabled:
                blockers.append("connection_disabled")
            revision = await session.scalar(
                select(ProviderConnectionRevision)
                .where(ProviderConnectionRevision.connection_id == connection.id)
                .order_by(ProviderConnectionRevision.revision_no.desc())
                .limit(1)
            )
            if revision is None:
                blockers.append("connection_revision_missing")
            else:
                evidence["connection_revision_id"] = str(revision.id)
                evidence["credential_revision_id"] = str(revision.credential_revision_id)
                if revision.credential_revision_id != connection.credential_id:
                    blockers.append("credential_revision_mismatch")

        target_kind: BindingTargetKind = "unresolved"
        if binding.binding_target_kind == "global_model":
            model = (
                await session.get(ModelCapabilityRevision, binding.model_capability_revision_id)
                if binding.model_capability_revision_id is not None
                else None
            )
            catalog = (
                await session.get(ModelCatalogEntry, binding.catalog_entry_id)
                if binding.catalog_entry_id is not None
                else None
            )
            legacy_manifest = catalog.capability_manifest_json if catalog is not None else None
            capability_manifest = (
                {key: value for key, value in legacy_manifest.items()
                 if key not in {"lifecycle", "catalog_source"}}
                if isinstance(legacy_manifest, dict)
                else None
            )
            if model is not None:
                evidence["global_manifest_hash"] = model.manifest_hash
                evidence["model_revision"] = model.model_revision
            if (
                model is not None
                and catalog is not None
                and isinstance(legacy_manifest, dict)
                and capability_manifest is not None
                and connection is not None
                and model.legacy_catalog_entry_id == catalog.id
                and binding.canonical_model_id == model.canonical_model_id
                and binding.model_id == model.canonical_model_id
                and binding.media_type == model.media_kind
                and connection.provider_type == model.provider_type
                and connection.protocol_profile == model.protocol_profile
                and catalog.provider_type == model.provider_type
                and catalog.protocol_profile == model.protocol_profile
                and catalog.model_id == model.canonical_model_id
                and catalog.model_revision == model.model_revision
                and catalog.media_kind == model.media_kind
                and capability_manifest.get("model_revision") == model.model_revision
                and capability_manifest.get("model_id") == model.canonical_model_id
                and binding.capability_manifest_hash == catalog.contract_manifest_hash
                and hash_manifest(legacy_manifest) == catalog.contract_manifest_hash
                and model.manifest_json == capability_manifest
                and model.manifest_hash == hash_manifest(capability_manifest)
                and binding.invoke_model_value is not None
                and binding.remote_resource_kind is not None
                and binding.remote_resource_id == binding.invoke_model_value
            ):
                target_kind = "global_model"
                evidence["source_snapshot_id"] = model.source_snapshot_id
                if model.source_snapshot_id is None:
                    blockers.append("source_snapshot_missing")
                if model.implementation_status != "contract_tested":
                    blockers.append("global_contract_not_tested")
                publication = await session.get(ModelPublicationState, model.id)
                if publication is None or publication.lifecycle not in {
                    "active",
                    "legacy",
                    "deprecated",
                }:
                    blockers.append("global_lifecycle_denies_create")
            else:
                blockers.append("global_target_unresolved")
        elif binding.binding_target_kind == "connection_model":
            discovered = (
                await session.get(ConnectionDiscoveredModel, binding.connection_discovered_model_id)
                if binding.connection_discovered_model_id is not None
                else None
            )
            capability = (
                await session.get(
                    ConnectionModelCapabilityRevision,
                    binding.connection_model_capability_revision_id,
                )
                if binding.connection_model_capability_revision_id is not None
                else None
            )
            if (
                discovered is not None
                and capability is not None
                and capability.connection_discovered_model_id == discovered.id
                and capability.workspace_id == workspace_id
                and discovered.connection_id == binding.connection_id
                and discovered.workspace_id == workspace_id
                and discovered.remote_model_id == binding.invoke_model_value
            ):
                target_kind = "connection_model"
                if capability.implementation_status != "contract_tested":
                    blockers.append("connection_contract_not_tested")
                if (
                    revision is None
                    or discovered.connection_revision_id != revision.id
                    or discovered.credential_revision_id != revision.credential_revision_id
                ):
                    blockers.append("discovery_revision_stale")
            else:
                blockers.append("connection_target_unresolved")
        else:
            blockers.append("binding_target_unresolved")

        availability = "not_checked"
        if binding.invoke_model_value is None:
            blockers.append("invoke_model_value_missing")
        elif revision is not None:
            projection = await session.scalar(
                select(ProviderModelAvailability).where(
                    ProviderModelAvailability.connection_revision_id == revision.id,
                    ProviderModelAvailability.credential_revision_id
                    == revision.credential_revision_id,
                    ProviderModelAvailability.remote_model_id == binding.invoke_model_value,
                    ProviderModelAvailability.workspace_id == workspace_id,
                )
            )
            if projection is not None:
                availability = projection.effective_status
                evidence["availability_evidence_id"] = str(projection.latest_evidence_id)
                evidence["positive_availability_evidence_id"] = (
                    str(projection.positive_evidence_id)
                    if projection.positive_evidence_id is not None
                    else None
                )
        if availability != "visible":
            blockers.append("availability_not_visible")
        rows.append(
            BindingCutoverRow(
                binding_id=binding.id,
                enabled=binding.enabled,
                connection_id=binding.connection_id,
                purpose=binding.purpose,
                model_id=binding.model_id,
                invoke_model_value=binding.invoke_model_value,
                target_kind=target_kind,
                model_capability_revision_id=binding.model_capability_revision_id,
                connection_discovered_model_id=binding.connection_discovered_model_id,
                connection_model_capability_revision_id=binding.connection_model_capability_revision_id,
                availability=availability,
                classification_evidence=evidence,
                blocking_reasons=tuple(blockers),
            )
        )
    return BindingCutoverReport(workspace_id=workspace_id, rows=tuple(rows))
