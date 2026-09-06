"""P4-02 ReferencePlanCompiler (07 §16 / 03 §32).

Translates shot-reference business *purposes* (identity / clothing / action /
camera_language / first_frame / last_frame / generic_reference / ...) into
ModelManifest input slots for the resolved capability, classifying each delivery
as ``exact`` / ``approximate`` / ``unsupported``.

Unsupported references are NEVER silently dropped: they are returned with
``delivery="unsupported"`` and surfaced as ``CapabilityGap`` entries so the plan
can fail closed or request explicit acceptance (P4-05 / P4-07).
"""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatch
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.production.execution_plan import (
    CapabilityGap,
    PlanDelivery,
    PlannedReference,
)
from app.providers.capabilities import Capability
from app.providers.manifest import InputSlotSpec, ModelManifest

# Business purpose -> canonical ModelManifest input-slot role.
PURPOSE_TO_ROLE: Final[dict[str, str]] = {
    "identity": "reference_image",
    "clothing": "reference_image",
    "pose": "reference_image",
    "style": "reference_image",
    "scene_layout": "reference_image",
    "scene_lighting": "reference_image",
    "generic_reference": "reference_image",
    "action": "reference_video",
    "camera_language": "reference_video",
    "audio_rhythm": "reference_audio",
    "first_frame": "first_frame",
    "last_frame": "last_frame",
}

# Purposes whose mapped role is semantically approximate: the model accepts the
# reference in that slot but the delivery is a convention, not a 1:1 contract.
APPROXIMATE_PURPOSES: Final[frozenset[str]] = frozenset(
    {
        "camera_language",
        "scene_layout",
        "scene_lighting",
        "style",
    }
)

_UNKNOWN_PURPOSE = "unknown reference purpose"
_SLOT_NOT_DECLARED = "model does not declare input slot for this reference role"
_MEDIA_MISMATCH = "reference media type does not match the declared input slot"
_EXCEEDS_CARDINALITY = "reference count exceeds the declared input slot maximum"
_EXCLUSIVE_GROUP = "references occupy mutually exclusive input-slot groups"


class ShotReferenceIntent(BaseModel):
    """One shot reference before capability translation (P4-02 input).

    Carries business purpose + artifact identity; never carries bytes/URLs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID | None = None
    purpose: str = Field(min_length=1, max_length=80)
    asset_version_id: UUID | None = None
    artifact_id: UUID | None = None
    resolution_mode: str = Field(default="current_formal", max_length=24)
    mime_type: str = Field(default="image/png", max_length=120)
    fingerprint: str | None = Field(default=None, max_length=128)


class ReferenceCompileResult(BaseModel):
    """Output of one capability-scoped reference compile."""

    planned_references: list[PlannedReference] = Field(default_factory=list)
    capability_gaps: list[CapabilityGap] = Field(default_factory=list)
    accepted_approximations: list[str] = Field(default_factory=list)

    @property
    def unsupported(self) -> list[PlannedReference]:
        return [r for r in self.planned_references if r.delivery == "unsupported"]

    @property
    def approximate(self) -> list[PlannedReference]:
        return [r for r in self.planned_references if r.delivery == "approximate"]


def _media_matches(media_types: list[str], mime_type: str) -> bool:
    if not media_types:
        return True
    return any(fnmatch(mime_type, pattern) for pattern in media_types)


def _input_slots(
    manifest: ModelManifest,
    capability: Capability,
    mode_id: str | None,
) -> dict[str, InputSlotSpec]:
    spec = manifest.capability_specs.get(capability)
    if spec is None:
        return {}
    return spec.mode_spec(mode_id).input_slots


def _to_planned(
    intent: ShotReferenceIntent,
    role: str | None,
    delivery: PlanDelivery,
    reason: str | None,
) -> PlannedReference:
    return PlannedReference(
        binding_id=intent.binding_id,
        purpose=intent.purpose,
        role=role,
        asset_version_id=intent.asset_version_id,
        artifact_id=intent.artifact_id,
        resolution_mode=intent.resolution_mode,
        mime_type=intent.mime_type,
        fingerprint=intent.fingerprint,
        delivery=delivery,
        reason=reason,
    )


def compile_references(
    *,
    manifest: ModelManifest,
    capability: Capability,
    references: Sequence[ShotReferenceIntent],
    mode_id: str | None = None,
    accept_approximations: bool = False,
) -> ReferenceCompileResult:
    """Classify every reference against the manifest input slots.

    - ``exact``: role declared, media compatible, cardinality within limit.
    - ``approximate``: same as exact but the purpose-to-role mapping is a
      convention (see APPROXIMATE_PURPOSES).
    - ``unsupported``: role missing / media mismatch / unknown purpose /
      cardinality exceeded / exclusive-group conflict. Never silently dropped.
    """
    spec = manifest.capability_specs.get(capability)
    result = ReferenceCompileResult()
    if spec is None:
        result.capability_gaps.append(
            CapabilityGap(
                capability=capability,
                controls=[],
                severity="fatal",
                reason=f"model manifest declares no capability {capability.value}",
            )
        )
        for intent in references:
            result.planned_references.append(
                _to_planned(intent, None, "unsupported", "capability unavailable in manifest")
            )
        return result

    slots = _input_slots(manifest, capability, mode_id)
    planned: list[PlannedReference] = []
    for intent in references:
        role = PURPOSE_TO_ROLE.get(intent.purpose)
        delivery: PlanDelivery = "exact"
        reason: str | None = None
        if role is None:
            delivery = "unsupported"
            reason = _UNKNOWN_PURPOSE
        else:
            slot = slots.get(role)
            if slot is None:
                delivery = "unsupported"
                reason = _SLOT_NOT_DECLARED
            elif not _media_matches(slot.media_types, intent.mime_type):
                delivery = "unsupported"
                reason = _MEDIA_MISMATCH
            elif intent.purpose in APPROXIMATE_PURPOSES:
                delivery = "approximate"
                reason = f"purpose {intent.purpose!r} delivered via {role} is a convention"
        planned.append(_to_planned(intent, role, delivery, reason))

    # Cardinality per role: mark the excess references unsupported.
    by_role: dict[str, list[int]] = {}
    for index, ref in enumerate(planned):
        if ref.role is not None:
            by_role.setdefault(ref.role, []).append(index)
    for role, indexes in by_role.items():
        slot = slots.get(role)
        if slot is None or slot.maximum is None:
            continue
        for index in indexes[slot.maximum:]:
            planned[index] = planned[index].model_copy(
                update={"delivery": "unsupported", "reason": _EXCEEDS_CARDINALITY}
            )

    # Mutually exclusive groups: at most one member per group may be used.
    for group in spec.constraints.mutually_exclusive:
        occupied_members: list[str] = []
        for member in group:
            if any(
                ref.role is not None and ref.role in member
                for ref in planned
                if ref.delivery != "unsupported"
            ):
                occupied_members.append(member)
        if len(occupied_members) > 1:
            result.capability_gaps.append(
                CapabilityGap(
                    capability=capability,
                    controls=sorted({ref.role for ref in planned if ref.role is not None}),
                    severity="fatal",
                    reason=_EXCLUSIVE_GROUP,
                )
            )
            for index, ref in enumerate(planned):
                if ref.delivery != "unsupported":
                    planned[index] = ref.model_copy(
                        update={"delivery": "unsupported", "reason": _EXCLUSIVE_GROUP}
                    )
            break

    result.planned_references = planned

    # Gaps: every unsupported reference is surfaced (never silently dropped).
    unsupported = result.unsupported
    if unsupported:
        result.capability_gaps.append(
            CapabilityGap(
                capability=capability,
                controls=sorted({ref.purpose for ref in unsupported}),
                severity="fatal",
                reason="unsupported references must be accepted or fail closed",
            )
        )

    # Approximations: only accepted when the caller opts in.
    approximate = result.approximate
    if approximate:
        if accept_approximations:
            result.accepted_approximations = [ref.purpose for ref in approximate]
        else:
            result.capability_gaps.append(
                CapabilityGap(
                    capability=capability,
                    controls=sorted({ref.purpose for ref in approximate}),
                    severity="warning",
                    reason="approximate references require explicit acceptance",
                )
            )
    return result
