"""Voice binding resolution: the project's voice model, never an instance engine.

The project media configuration names one voice ``ProviderModelBinding``. This module
resolves it into a read-only status projection: ``configured`` (enabled, voice media
kind, catalog entry present), ``unavailable`` (a saved choice that cannot run now) or
``missing`` (nothing configured). It never falls back to another engine or model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.models import ProviderModelBinding


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


def _missing() -> VoiceBindingStatus:
    return VoiceBindingStatus(
        status="missing",
        binding_id=None,
        model_id=None,
        provider_type=None,
        voice_options={},
        reason_code="VOICE_BINDING_MISSING",
    )


def _unavailable(
    *, binding: ProviderModelBinding, reason: str
) -> VoiceBindingStatus:
    return VoiceBindingStatus(
        status="unavailable",
        binding_id=binding.id,
        model_id=binding.model_id,
        provider_type=None,
        voice_options={},
        reason_code=reason,
    )


async def resolve_voice_binding(
    session: AsyncSession, *, project: Project
) -> VoiceBindingStatus:
    profile = await ProductionModelProfileService(session).get_effective_for_project(
        project=project
    )
    if profile is None or profile.voice_model_binding_id is None:
        return _missing()
    binding = await session.get(ProviderModelBinding, profile.voice_model_binding_id)
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
        await session.get(ModelCatalogEntry, binding.catalog_entry_id)
        if binding.catalog_entry_id is not None
        else None
    )
    if entry is None or entry.media_kind != "voice":
        return _unavailable(binding=binding, reason="VOICE_CATALOG_MISSING")
    return VoiceBindingStatus(
        status="configured",
        binding_id=binding.id,
        model_id=binding.model_id,
        provider_type=entry.provider_type,
        voice_options=dict(profile.voice_options),
        reason_code=None,
        protocol_profile=entry.protocol_profile,
        manifest_hash=entry.contract_manifest_hash,
    )


__all__ = ["VoiceBindingStatus", "resolve_voice_binding"]
