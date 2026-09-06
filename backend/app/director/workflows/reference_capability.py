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

from collections.abc import Mapping
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


# ---------------------------------------------------------------------------
# Dispatch-time fail-closed gate (G-WF-05 / G-WF-06 enforcement).
#
# The planning surfaces above are advisory.  The reference *compiler* is the
# only authoritative boundary: if a shot's frozen participation plan records
# more visible controlled subjects than the resolved model's catalog manifest
# can carry as reference images, the keyframe must not be submitted.  A silent
# single-reference POST would prove only character A survived, which is exactly
# the "只发角色 A 后宣称 multi-character PASS" outcome the gate exists to forbid.
#
# These functions are pure reads over data already in scope on the dispatch
# path (a snapshot dict carrying the frozen participations and the resolved
# catalog operational manifest).  They never touch a Provider and never mutate
# anything.
# ---------------------------------------------------------------------------


def visible_subject_count_from_snapshot(snapshot: Mapping[str, object]) -> int:
    """Count visible controlled subjects from a frozen ``workflow_participations``.

    Returns 0 when the snapshot carries no participation plan, so a shot without
    a plan is never gated (it resolves to the single canonical reference the
    pipeline already handles).
    """
    raw = snapshot.get("workflow_participations")
    if raw is None:
        return 0
    entries = raw if isinstance(raw, list) else None
    if entries is None:
        return 0
    count = 0
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        screen_role = str(item.get("screen_role") or "")
        # A plan bound at planning time is authoritative: any non-offscreen entry
        # occupies the frame; bag-of-streams serialization already dropped offscreen.
        if screen_role != "offscreen":
            count += 1
    return count


def max_subject_references_from_catalog_manifest(
    operations: Mapping[str, object],
) -> int:
    """Max ``reference_image`` subjects the resolved catalog operation allows.

    ``operations`` is the resolved ``ModelCapabilityManifest.operations`` dict on
    the dispatch path.  Each value may be an :class:`OperationManifest` pydantic
    model (the in-memory form) or an already-``model_dump``-ed dict.  Absent /
    unparsed constraints return 0 (fail closed: an undocumented slot is treated
    as unsupported rather than silently allowed).
    """
    op = operations.get("image.generate")
    if op is None:
        return 0
    # Pydantic model form: ``op.reference_constraints`` is a dict of models.
    if not isinstance(op, Mapping):
        constraints: object | None = getattr(op, "reference_constraints", None)
        if isinstance(constraints, Mapping):
            ref = constraints.get("reference_image")
            if isinstance(ref, Mapping):
                maximum = ref.get("max")
                if isinstance(maximum, int):
                    return maximum
            # Orm model attribute access for a non-Mapping reference model.
            ref_model = constraints.get("reference_image")
            ref_max = getattr(ref_model, "max", None)
            if isinstance(ref_max, int):
                return ref_max
        return 0
    constraints = op.get("reference_constraints")
    if not isinstance(constraints, Mapping):
        return 0
    ref = constraints.get("reference_image")
    if not isinstance(ref, Mapping):
        return 0
    maximum = ref.get("max")
    if not isinstance(maximum, int):
        return 0
    return maximum


def dispatch_capability_gate(
    *,
    snapshot: Mapping[str, object],
    operations: Mapping[str, object],
    accept_approximations: bool = False,
    staged_strategy_id: str | None = None,
) -> ReferenceCapabilityAssessment | None:
    """Decide whether keyframe dispatch may submit for a multi-subject shot.

    Mirrors :func:`assess_multi_character_capability` but on the dispatch path's
    own inputs (snapshot participations + catalog operational manifest).  Returns
    ``None`` when the shot is not a multi-subject shot (no plan, or the plan's
    subjects fit within the model limit) — the caller proceeds normally.  Returns
    an ``UNSUPPORTED``/``APPROXIMATE`` assessment when dispatch must stop.
    """
    required = visible_subject_count_from_snapshot(snapshot)
    if required <= 1:
        # 0 or 1 subject: the pipeline's single canonical reference is correct.
        return None
    maximum = max_subject_references_from_catalog_manifest(operations)
    if required <= maximum:
        return None
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

