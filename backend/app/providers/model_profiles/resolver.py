"""ModelBindingResolver (spec §15–§16, §62–§65, §134 rules 5–7).

Resolution priority is fixed: request override → project profile → workspace
default → system default → error. The resolver only *reads configuration and
validates against the registry* — it never calls a Provider, never generates,
never polls (spec §63). A profile binding that exists for the slot but whose
model cannot serve the requested capability fails fast with
``PROFILE_MODEL_CAPABILITY_MISMATCH`` instead of silently falling to the next
source (spec §44, §122 — no silent model switch).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.capabilities import Capability
from app.providers.model_profiles.errors import (
    profile_capability_mismatch,
    profile_no_available_model,
)
from app.providers.model_profiles.models import (
    ModelSlotBinding,
    ResolvedModelBinding,
)
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.service import parse_bindings
from app.providers.model_profiles.slots import ModelSlot
from app.providers.registry import ModelRegistry, RegisteredModel
from app.providers.selector import DefaultModelSelector


class ModelBindingResolver:
    """Resolves a (slot, capability) to the effective model for a project."""

    def __init__(
        self,
        session: AsyncSession,
        registry: ModelRegistry | None = None,
    ) -> None:
        self._session = session
        if registry is None:
            from app.providers.model_profiles.service import default_model_registry

            self._registry = default_model_registry()
        else:
            self._registry = registry
        self._selector = DefaultModelSelector()

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        slot: ModelSlot,
        capability: Capability,
        requested_model_id: str | None = None,
    ) -> ResolvedModelBinding:
        """Return the effective binding. Raises a stable model-profile error when
        the requested model is unknown, a bound model cannot serve the
        capability, or no model is available anywhere."""
        # 1. Request explicit override (spec §15 top priority).
        if requested_model_id is not None:
            model = self._require_model(requested_model_id)
            if capability not in model.manifest.capability_specs:
                # Same error the CapabilityRouter would raise at dispatch time.
                from app.providers.errors import UnsupportedCapabilityError

                raise UnsupportedCapabilityError(capability)
            return ResolvedModelBinding(
                slot=slot,
                capability=capability,
                model_id=model.manifest.id,
                source="request_override",
                native_options={},
            )

        # 2. Project profile → 3. workspace default (same validation path).
        profile = await self._project_or_workspace_profile(
            workspace_id=workspace_id, project_id=project_id
        )
        if profile is not None:
            binding = self._profile_binding_for(profile, slot)
            if binding is not None:
                return self._resolve_profile_binding(
                    binding,
                    slot=slot,
                    capability=capability,
                    profile=profile,
                )

        # 4. System default: first registered model satisfying the capability.
        return self._resolve_system_default(slot=slot, capability=capability)

    async def _project_or_workspace_profile(
        self, *, workspace_id: UUID, project_id: UUID | None
    ) -> ProductionModelProfile | None:
        """Project profile, else workspace default. None when neither exists."""
        from typing import cast

        from sqlalchemy import select

        if project_id is not None:
            profile = cast(
                "ProductionModelProfile | None",
                await self._session.scalar(
                    select(ProductionModelProfile).where(
                        ProductionModelProfile.project_id == project_id
                    )
                ),
            )
            if profile is not None:
                return profile
        return cast(
            "ProductionModelProfile | None",
            await self._session.scalar(
                select(ProductionModelProfile).where(
                    ProductionModelProfile.workspace_id == workspace_id,
                    ProductionModelProfile.project_id.is_(None),
                    ProductionModelProfile.is_default.is_(True),
                )
            ),
        )

    @staticmethod
    def _profile_binding_for(
        profile: ProductionModelProfile, slot: ModelSlot
    ) -> ModelSlotBinding | None:
        binding = parse_bindings(profile.bindings).get(slot)
        if binding is None or not binding.enabled:
            return None
        return binding

    def _resolve_profile_binding(
        self,
        binding: ModelSlotBinding,
        *,
        slot: ModelSlot,
        capability: Capability,
        profile: ProductionModelProfile,
    ) -> ResolvedModelBinding:
        model = self._require_model(binding.model_id)
        self._require_capability(
            model, binding.model_id, slot, capability,
            fail_on_mismatch=True,
        )
        return ResolvedModelBinding(
            slot=slot,
            capability=capability,
            model_id=model.manifest.id,
            source="project_profile" if profile.project_id is not None else "workspace_profile",
            profile_id=profile.id,
            profile_version=profile.version,
            native_options=binding.native_options,
        )

    def _resolve_system_default(
        self, *, slot: ModelSlot, capability: Capability
    ) -> ResolvedModelBinding:
        try:
            model = self._selector.select(
                capability=capability,
                requested_model=None,
                registry=self._registry,
            )
        except Exception as exc:  # noqa: BLE001 - no model -> stable error
            raise profile_no_available_model(str(capability)) from exc
        return ResolvedModelBinding(
            slot=slot,
            capability=capability,
            model_id=model.manifest.id,
            source="system_default",
            native_options={},
        )

    def _require_model(self, model_id: str) -> RegisteredModel:
        from app.providers.model_profiles.errors import profile_model_not_found

        model = self._registry.get_or_none(model_id)
        if model is None:
            raise profile_model_not_found(model_id)
        return model

    def _require_capability(
        self,
        model: RegisteredModel,
        model_id: str,
        slot: ModelSlot,
        capability: Capability,
        *,
        fail_on_mismatch: bool = False,
    ) -> None:
        if capability in model.manifest.capability_specs:
            return
        if fail_on_mismatch:
            raise profile_capability_mismatch(
                str(slot), model_id, capability=str(capability)
            )
