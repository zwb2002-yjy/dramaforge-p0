"""Voice binding resolution: the project's voice model, never an instance engine.

The project media configuration names one voice ``ProviderModelBinding``. This module
resolves it into a read-only status projection: ``configured`` (enabled, voice media
kind, catalog entry present), ``unavailable`` (a saved choice that cannot run now) or
``missing`` (nothing configured). It never falls back to another engine or model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.egress_admission import EgressAdmission
from app.access.egress_models import ProviderDestinationRevision
from app.access.models import Project
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.connection_service import ProviderConnectionService
from app.providers.destinations import destination_configuration_hash
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.models import ProviderConnection, ProviderModelBinding


@dataclass(frozen=True)
class VoiceBindingStatus:
    status: Literal["configured", "unavailable", "missing"]
    binding_id: UUID | None
    model_id: str | None
    provider_type: str | None
    voice_options: dict[str, object]
    reason_code: str | None
    protocol_profile: str | None = None
    manifest_hash: str | None = None
    connection_revision_id: UUID | None = None
    destination_revision_id: UUID | None = None
    policy_revision_id: UUID | None = None
    voices: list[str] = field(default_factory=list)


def _missing() -> VoiceBindingStatus:
    return VoiceBindingStatus(
        status="missing",
        binding_id=None,
        model_id=None,
        provider_type=None,
        voice_options={},
        reason_code="VOICE_BINDING_MISSING",
    )


def _unavailable(*, binding: ProviderModelBinding, reason: str) -> VoiceBindingStatus:
    return VoiceBindingStatus(
        status="unavailable",
        binding_id=binding.id,
        model_id=binding.model_id,
        provider_type=None,
        voice_options={},
        reason_code=reason,
    )


def _voice_ids(schema: object) -> list[str]:
    if not isinstance(schema, dict):
        return []
    raw = schema.get("voices")
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    return ids


async def resolve_voice_binding(session: AsyncSession, *, project: Project) -> VoiceBindingStatus:
    profile = await ProductionModelProfileService(session).get_effective_for_project(
        project=project
    )
    if profile is None or profile.voice_model_binding_id is None:
        return _missing()
    binding = await session.get(
        ProviderModelBinding, profile.voice_model_binding_id, populate_existing=True
    )
    if binding is None or binding.workspace_id != project.workspace_id:
        return VoiceBindingStatus(
            status="unavailable",
            binding_id=profile.voice_model_binding_id,
            model_id=None,
            provider_type=None,
            voice_options={},
            reason_code="VOICE_BINDING_NOT_FOUND",
        )
    if not binding.enabled:
        return _unavailable(binding=binding, reason="VOICE_BINDING_DISABLED")
    if binding.media_type != "voice" or binding.purpose != "voice":
        return _unavailable(binding=binding, reason="VOICE_BINDING_KIND_MISMATCH")
    entry = (
        await session.get(ModelCatalogEntry, binding.catalog_entry_id, populate_existing=True)
        if binding.catalog_entry_id is not None
        else None
    )
    if entry is None or entry.media_kind != "voice":
        return _unavailable(binding=binding, reason="VOICE_CATALOG_MISSING")
    connection = await session.get(
        ProviderConnection, binding.connection_id, populate_existing=True
    )
    if not connection or not connection.enabled or connection.workspace_id != project.workspace_id:
        return _unavailable(binding=binding, reason="VOICE_CONNECTION_UNAVAILABLE")
    revision = await ProviderConnectionService(session).current_connection_revision(
        connection=connection
    )
    if (
        revision.base_url != connection.base_url
        or revision.credential_revision_id != connection.credential_id
    ):
        return _unavailable(binding=binding, reason="VOICE_CONNECTION_CHANGED")
    destination = await session.scalar(
        select(ProviderDestinationRevision)
        .where(
            ProviderDestinationRevision.workspace_id == project.workspace_id,
            ProviderDestinationRevision.binding_ref == str(binding.id),
        )
        .order_by(ProviderDestinationRevision.revision.desc())
        .limit(1)
    )
    if destination and destination.configuration_hash != destination_configuration_hash(
        binding, connection
    ):
        return _unavailable(binding=binding, reason="VOICE_DESTINATION_CHANGED")
    admission = await EgressAdmission(session).decide(
        project,
        purpose="voice_generation",
        destination_id=destination.id if destination else None,
    )
    if not admission.allowed:
        return _unavailable(binding=binding, reason=admission.reason_code)
    return VoiceBindingStatus(
        status="configured",
        connection_revision_id=revision.id,
        destination_revision_id=admission.destination_revision_id,
        policy_revision_id=admission.policy_revision_id,
        binding_id=binding.id,
        model_id=binding.model_id,
        provider_type=entry.provider_type,
        voice_options=dict(profile.voice_options),
        reason_code=None,
        protocol_profile=entry.protocol_profile,
        manifest_hash=entry.contract_manifest_hash,
        voices=_voice_ids(entry.option_schema_json),
    )


__all__ = ["VoiceBindingStatus", "resolve_voice_binding"]
