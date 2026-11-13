"""Shared reference-capacity contract for planning and frozen production inputs.

Pure value assessment only: no provider, Director, persistence or lifecycle imports.
Planning adapters and production admission consume this single policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

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


def assess_reference_capacity(
    *,
    required: int,
    maximum: int,
    accept_approximations: bool = False,
    staged_strategy_id: str | None = None,
) -> ReferenceCapabilityAssessment:
    """Assess counts with the same explicit strategy consent in every caller."""
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
    """Assess frozen dispatch inputs; None preserves the single-subject path.

    An assessment is a stop/adaptation result, never permission to submit a request.
    """
    required = visible_subject_count_from_snapshot(snapshot)
    if required <= 1:
        return None
    assessment = assess_reference_capacity(
        required=required,
        maximum=max_subject_references_from_catalog_manifest(operations),
        accept_approximations=accept_approximations,
        staged_strategy_id=staged_strategy_id,
    )
    return None if assessment.status is MultiCharacterCapabilityStatus.EXACT else assessment
