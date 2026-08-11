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


def _first_candidate_preferring_bridge(
    candidates: list[RegisteredModel],
) -> RegisteredModel:
    for model in candidates:
        if model.manifest.metadata.get("bootstrap_bridge"):
            return model
    return candidates[0]


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
        # Deterministic system default: stable sort order first match. When a
        # bootstrap bridge is registered (e.g. the ``litellm/text-llm`` legacy
        # bridge alongside logical aliases), prefer it so the last-resort text
        # default keeps pointing at the bridge, not a logical alias that may be
        # unconfigured on the gateway (fix spec §34/§103).
        return _first_candidate_preferring_bridge(candidates)
