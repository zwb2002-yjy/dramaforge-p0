"""Default model selector (spec §34).

Priority: requested model → project/workspace default → system default → error.
P0 keeps a deterministic system default: the first registered model (stable
sort) that satisfies the capability. Project/workspace defaults are resolved by
the DB-bound service layer (Phase 11); until then the selector only handles the
explicit request and the system default. ``policy`` is accepted for signature
compatibility; smart routing/fallback is a P1 concern (spec §36/§37 — P0 never
auto-falls back).
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
        policy: object | None = None,
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
        # Deterministic system default: stable sort order first match.
        return candidates[0]
