"""Planning adapter for the shared multi-character reference-capacity contract."""

from __future__ import annotations

from app.contracts import reference_capability as capacity
from app.director.workflows.character_participation import ShotParticipationPlan
from app.providers.capabilities import Capability
from app.providers.manifest import ModelManifest


def required_subject_references(plan: ShotParticipationPlan) -> int:
    """Number of distinct visible controlled characters that need identity refs."""
    return plan.visible_controlled_count


def max_subject_references(
    manifest: ModelManifest,
    capability: Capability,
    mode_id: str | None,
) -> int:
    """Maximum subject (identity) references the model supports for a capability."""
    spec = manifest.capability_specs.get(capability)
    if spec is None:
        return 0
    slot = spec.mode_spec(mode_id).input_slots.get(capacity.SUBJECT_REFERENCE_ROLE)
    if slot is None:
        return 0
    if slot.maximum is None:
        return 2**31 - 1  # effectively unbounded
    return slot.maximum


def assess_multi_character_capability(
    *,
    manifest: ModelManifest,
    capability: Capability,
    mode_id: str | None,
    plan: ShotParticipationPlan,
    accept_approximations: bool = False,
    staged_strategy_id: str | None = None,
) -> capacity.ReferenceCapabilityAssessment:
    """Translate planning inputs into the shared capacity and consent contract."""
    return capacity.assess_reference_capacity(
        required=required_subject_references(plan),
        maximum=max_subject_references(manifest, capability, mode_id),
        accept_approximations=accept_approximations,
        staged_strategy_id=staged_strategy_id,
    )
