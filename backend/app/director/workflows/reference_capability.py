"""Multi-character reference / capability gate (WF6).

From planning to Provider compile, every visible character's identity reference
must be preserved.  If the resolved model cannot honor the number of distinct
subject references required by a shot's participation plan, the plan must fail
closed (``UNSUPPORTED`` -> Provider POST = 0).  A silently "dropped" secondary
character is never allowed (G-WF-05 / G-WF-06).

``APPROXIMATE`` is only allowed when an explicit registered staged strategy is
accepted by the user (never hidden).  ``EXACT`` means the model natively
supports the required subject bindings.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.director.workflows.character_participation import ShotParticipationPlan
from app.providers.capabilities import Capability
from app.providers.manifest import ModelManifest

# Reference-role name that carries a subject (identity) image in the manifest.
SUBJECT_REFERENCE_ROLE = "reference_image"

# Known staged strategies that may approximate multi-character control, only with
# explicit user acceptance.  This is an allowlist, not an automatic fallback.
REGISTERED_STAGED_STRATEGIES: dict[str, str] = {
    "two-pass-i2i-stabilize-v1": (
        "Generate the two-character framing once, then stabilize each subject "
        "identity via a second image-to-image pass."
    ),
    "lock-a-primary-then-i2i-b": (
        "Lock character A frame, then inject character B identity via i2i."
    ),
}


class MultiCharacterCapabilityStatus(StrEnum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    UNSUPPORTED = "UNSUPPORTED"


class ReferenceCapabilityAssessment(BaseModel):
    """Outcome of checking a model's multi-character reference support."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: MultiCharacterCapabilityStatus
    required_subject_references: int
    max_subject_references: int
    reason: str
    approximate_strategy_id: str | None = None
    approximate_strategy_description: str | None = None


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
    slot = spec.mode_spec(mode_id).input_slots.get(SUBJECT_REFERENCE_ROLE)
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
) -> ReferenceCapabilityAssessment:
    """Assess whether the model can preserve every subject reference.

    - ``EXACT`` when the model natively supports all required subjects.
    - ``UNSUPPORTED`` when it cannot and no approved staged strategy is accepted
      (fail closed; Provider POST must be 0).
    - ``APPROXIMATE`` only when a registered strategy is explicitly accepted.
    """
    required = required_subject_references(plan)
    maximum = max_subject_references(manifest, capability, mode_id)
    if required <= maximum:
        return ReferenceCapabilityAssessment(
            status=MultiCharacterCapabilityStatus.EXACT,
            required_subject_references=required,
            max_subject_references=maximum,
            reason="model natively supports all required subject references",
        )
    if accept_approximations and staged_strategy_id in REGISTERED_STAGED_STRATEGIES:
        return ReferenceCapabilityAssessment(
            status=MultiCharacterCapabilityStatus.APPROXIMATE,
            required_subject_references=required,
            max_subject_references=maximum,
            reason="model cannot natively bind all subjects; using an accepted staged strategy",
            approximate_strategy_id=staged_strategy_id,
            approximate_strategy_description=REGISTERED_STAGED_STRATEGIES[staged_strategy_id],
        )
    return ReferenceCapabilityAssessment(
        status=MultiCharacterCapabilityStatus.UNSUPPORTED,
        required_subject_references=required,
        max_subject_references=maximum,
        reason=(
            f"model supports {maximum} subject reference(s) but the shot requires "
            f"{required}; multi-character identity cannot be preserved"
        ),
    )
