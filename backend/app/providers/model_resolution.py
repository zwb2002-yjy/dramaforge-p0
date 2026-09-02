"""Reviewed concrete model resolution for Professional execution.

The resolver is the only business-level authority that turns a requested/profile
model into one credentialed ProviderModelBinding.  It returns a typed plan-time
result only; compilers and runtimes consume the frozen result and never choose a
replacement model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.model_profiles.models import ModelSlotBinding
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.service import parse_bindings
from app.providers.model_profiles.slots import ModelSlot
from app.providers.models import ProjectProviderBinding, ProviderConnection, ProviderModelBinding

ResolutionSource = Literal[
    "request_override",
    "project_profile",
    "workspace_profile",
    "system_default",
    "fallback",
]
ResolutionStatus = Literal["RESOLVED", "UNAVAILABLE", "FALLBACK"]


class ExecutionModelResolution(BaseModel):
    """Frozen, secret-free concrete model identity for one execution."""

    requested_model_id: str | None = None
    resolved_model_id: str | None = None
    source: ResolutionSource
    status: ResolutionStatus
    reason: str | None = None

    provider_model_binding_id: UUID | None = None
    provider_connection_id: UUID | None = None
    provider_connection_revision_id: UUID | None = None
    credential_revision_id: UUID | None = None
    catalog_entry_id: UUID | None = None
    model_revision: str | None = None
    manifest_hash: str | None = None
    invoke_model_value: str | None = None

    capability: Capability
    mode_id: str | None = None
    native_options: dict[str, object] = Field(default_factory=dict)


@dataclass(frozen=True)
class _ConcreteBinding:
    binding: ProviderModelBinding
    connection: ProviderConnection
    catalog_entry: ModelCatalogEntry | None


class ExecutionModelResolver:
    """Resolve a Professional execution to one concrete ProviderModelBinding.

    The priority is intentionally evaluated at *slot* level: explicit request,
    project profile slot, workspace profile slot, then an explicitly saved
    project binding as the system default. Once a higher-priority source names
    X, an unavailable X is terminal and never falls through to another model.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(
        self,
        *,
        project: Project,
        slot: ModelSlot,
        capability: Capability,
        purpose: str,
        mode_id: str | None,
        requested_model_id: str | None = None,
        requested_binding_id: UUID | None = None,
    ) -> ExecutionModelResolution:
        if requested_binding_id is not None:
            concrete = await self._binding_by_id(
                workspace_id=project.workspace_id,
                binding_id=requested_binding_id,
                purpose=purpose,
            )
            requested = (
                self._model_identity(concrete)
                if concrete is not None
                else requested_model_id
            )
            return self._resolution_for(
                concrete=concrete,
                requested_model_id=requested,
                source="request_override",
                capability=capability,
                mode_id=mode_id,
                native_options={},
            )

        if requested_model_id is not None:
            concrete = await self._binding_for_model(
                workspace_id=project.workspace_id,
                model_id=requested_model_id,
                purpose=purpose,
            )
            return self._resolution_for(
                concrete=concrete,
                requested_model_id=requested_model_id,
                source="request_override",
                capability=capability,
                mode_id=mode_id,
                native_options={},
            )

        project_slot = await self._profile_slot_binding(
            workspace_id=project.workspace_id,
            project_id=project.id,
            slot=slot,
        )
        if project_slot is not None:
            profile, binding = project_slot
            concrete = await self._binding_for_model(
                workspace_id=project.workspace_id,
                model_id=binding.model_id,
                purpose=purpose,
            )
            return self._resolution_for(
                concrete=concrete,
                requested_model_id=binding.model_id,
                source="project_profile",
                capability=capability,
                mode_id=mode_id,
                native_options=binding.native_options,
            )

        workspace_slot = await self._workspace_slot_binding(
            workspace_id=project.workspace_id,
            slot=slot,
        )
        if workspace_slot is not None:
            profile, binding = workspace_slot
            concrete = await self._binding_for_model(
                workspace_id=project.workspace_id,
                model_id=binding.model_id,
                purpose=purpose,
            )
            return self._resolution_for(
                concrete=concrete,
                requested_model_id=binding.model_id,
                source="workspace_profile",
                capability=capability,
                mode_id=mode_id,
                native_options=binding.native_options,
            )

        # An explicitly saved project binding is used only when neither profile
        # declares this slot. It is labelled system_default and never acts as a
        # fallback after a higher-priority model was selected.
        project_binding = await self._session.scalar(
            select(ProjectProviderBinding).where(
                ProjectProviderBinding.project_id == project.id,
                ProjectProviderBinding.purpose == purpose,
            )
        )
        concrete = (
            await self._binding_by_id(
                workspace_id=project.workspace_id,
                binding_id=project_binding.model_binding_id,
                purpose=purpose,
            )
            if project_binding is not None
            else None
        )
        return self._resolution_for(
            concrete=concrete,
            requested_model_id=self._model_identity(concrete),
            source="system_default",
            capability=capability,
            mode_id=mode_id,
            native_options={},
            missing_reason="MODEL_BINDING_MISSING",
        )

    async def _profile_slot_binding(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        slot: ModelSlot,
    ) -> tuple[ProductionModelProfile, ModelSlotBinding] | None:
        profile = await self._session.scalar(
            select(ProductionModelProfile).where(
                ProductionModelProfile.workspace_id == workspace_id,
                ProductionModelProfile.project_id == project_id,
            )
        )
        return self._slot_from_profile(profile, slot)

    async def _workspace_slot_binding(
        self, *, workspace_id: UUID, slot: ModelSlot
    ) -> tuple[ProductionModelProfile, ModelSlotBinding] | None:
        profile = await self._session.scalar(
            select(ProductionModelProfile).where(
                ProductionModelProfile.workspace_id == workspace_id,
                ProductionModelProfile.project_id.is_(None),
                ProductionModelProfile.is_default.is_(True),
            )
        )
        return self._slot_from_profile(profile, slot)

    @staticmethod
    def _slot_from_profile(
        profile: ProductionModelProfile | None, slot: ModelSlot
    ) -> tuple[ProductionModelProfile, ModelSlotBinding] | None:
        if profile is None:
            return None
        binding = parse_bindings(profile.bindings).get(slot)
        if binding is None or not binding.enabled:
            return None
        return profile, binding

    async def _binding_by_id(
        self, *, workspace_id: UUID, binding_id: UUID, purpose: str
    ) -> _ConcreteBinding | None:
        return await self._query_binding(
            workspace_id=workspace_id,
            purpose=purpose,
            binding_id=binding_id,
            model_id=None,
        )

    async def _binding_for_model(
        self, *, workspace_id: UUID, model_id: str, purpose: str
    ) -> _ConcreteBinding | None:
        provider_type, raw_model_id = self._split_model_id(model_id)
        return await self._query_binding(
            workspace_id=workspace_id,
            purpose=purpose,
            binding_id=None,
            model_id=raw_model_id,
            provider_type=provider_type,
        )

    async def _query_binding(
        self,
        *,
        workspace_id: UUID,
        purpose: str,
        binding_id: UUID | None,
        model_id: str | None,
        provider_type: str | None = None,
    ) -> _ConcreteBinding | None:
        statement = (
            select(ProviderModelBinding, ProviderConnection, ModelCatalogEntry)
            .join(ProviderConnection, ProviderConnection.id == ProviderModelBinding.connection_id)
            .outerjoin(
                ModelCatalogEntry,
                ModelCatalogEntry.id == ProviderModelBinding.catalog_entry_id,
            )
            .where(
                ProviderModelBinding.workspace_id == workspace_id,
                ProviderModelBinding.purpose == purpose,
                ProviderModelBinding.enabled.is_(True),
                ProviderConnection.enabled.is_(True),
            )
            .order_by(ProviderModelBinding.updated_at.desc())
        )
        if binding_id is not None:
            statement = statement.where(ProviderModelBinding.id == binding_id)
        if model_id is not None:
            statement = statement.where(ProviderModelBinding.model_id == model_id)
        if provider_type is not None:
            statement = statement.where(ProviderConnection.provider_type == provider_type)
        row = (await self._session.execute(statement)).first()
        if row is None:
            return None
        binding, connection, catalog_entry = row
        return _ConcreteBinding(
            binding=binding,
            connection=connection,
            catalog_entry=catalog_entry,
        )

    def _resolution_for(
        self,
        *,
        concrete: _ConcreteBinding | None,
        requested_model_id: str | None,
        source: ResolutionSource,
        capability: Capability,
        mode_id: str | None,
        native_options: dict[str, object],
        missing_reason: str = "MODEL_BINDING_UNAVAILABLE",
    ) -> ExecutionModelResolution:
        if concrete is None:
            return ExecutionModelResolution(
                requested_model_id=requested_model_id,
                source=source,
                status="UNAVAILABLE",
                reason=missing_reason,
                capability=capability,
                mode_id=mode_id,
                native_options=native_options,
            )
        entry = concrete.catalog_entry
        if entry is None:
            return ExecutionModelResolution(
                requested_model_id=requested_model_id,
                source=source,
                status="UNAVAILABLE",
                reason="MODEL_CATALOG_ENTRY_UNAVAILABLE",
                provider_model_binding_id=concrete.binding.id,
                provider_connection_id=concrete.connection.id,
                capability=capability,
                mode_id=mode_id,
                native_options=native_options,
            )
        return ExecutionModelResolution(
            requested_model_id=requested_model_id,
            resolved_model_id=self._model_identity(concrete),
            source=source,
            status="RESOLVED",
            provider_model_binding_id=concrete.binding.id,
            provider_connection_id=concrete.connection.id,
            catalog_entry_id=entry.id,
            model_revision=entry.model_revision,
            manifest_hash=entry.contract_manifest_hash,
            invoke_model_value=concrete.binding.invoke_model_value,
            capability=capability,
            mode_id=mode_id,
            native_options=native_options,
        )

    @staticmethod
    def _model_identity(concrete: _ConcreteBinding | None) -> str | None:
        if concrete is None:
            return None
        return f"{concrete.connection.provider_type}/{concrete.binding.model_id}"

    @staticmethod
    def _split_model_id(model_id: str) -> tuple[str | None, str]:
        provider_type, separator, raw_model_id = model_id.partition("/")
        if separator and provider_type and raw_model_id:
            return provider_type, raw_model_id
        return None, model_id
