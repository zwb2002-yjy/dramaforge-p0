"""Default model selector (spec §34).

Priority: requested model → project/workspace default → system default → error.
P0 keeps a deterministic system default: the first registered model (stable
sort) that satisfies the capability. Project/workspace defaults are resolved by
the DB-bound service layer; this selector handles only an explicit request or
one unambiguous system default. Smart routing and implicit fallback are not part
of the current contract.
"""

from __future__ import annotations

from app.providers.capabilities import Capability
from app.providers.errors import UnsupportedCapabilityError
from app.providers.registry import ModelRegistry, RegisteredModel, UnknownModelError


class DefaultModelSelector:
    def select(
        self,
        *,
        capability: Capability,
        requested_model: str | None,
        registry: ModelRegistry,
    ) -> RegisteredModel:
        if requested_model is not None:
            model = registry.get_or_none(requested_model)
            if model is None:
                raise UnknownModelError(requested_model)
            if capability not in model.manifest.capability_specs:
                raise UnsupportedCapabilityError(capability)
            return model
        candidates = registry.find_by_capability(capability)
        if not candidates:
            raise UnsupportedCapabilityError(capability)
        if capability == Capability.TEXT_GENERATE:
            from app.config import get_settings

            configured = f"litellm/{get_settings().litellm_text_gateway_model}"
            model = registry.get_or_none(configured)
            if model is None:
                raise UnknownModelError(configured)
            return model
        if len(candidates) != 1:
            raise UnknownModelError("explicit model selection is required")
        return candidates[0]
