"""Intent normalizer: derive capability requirements from a structured intent.

References are the source of truth; the required capability set is a derived,
auditable constraint. Caller-declared capabilities are unioned with the derived
set. Conflicts (duplicate reference roles over the manifest limit, impossible
normalization) fail before model selection so a "passed a last-frame but forgot
to declare it" bypass cannot occur.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    VideoGenerationIntentV1,
)
from app.providers.reference_roles import ReferenceRole, canonical_reference_role

_ROLE_TO_CAPABILITY = {
    ReferenceRole.FIRST_FRAME.value: "video.i2v.first_frame",
    ReferenceRole.LAST_FRAME.value: "video.i2v.last_frame",
    ReferenceRole.REFERENCE_IMAGE.value: "video.reference.image",
    ReferenceRole.REFERENCE_VIDEO.value: "video.reference.video",
    ReferenceRole.REFERENCE_AUDIO.value: "video.reference.audio",
}


@dataclass(frozen=True)
class NormalizationResult:
    required_capabilities: frozenset[str] = frozenset()
    reference_roles: frozenset[str] = frozenset()
    preferred_capabilities: frozenset[str] = frozenset()
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_reference_roles(
    references: list[ArtifactReferenceIntent],
) -> tuple[frozenset[str], list[str]]:
    """Derive required capabilities and reference roles; detect duplicates."""
    capabilities: set[str] = set()
    roles: set[str] = set()
    errors: list[str] = []
    for ref in references:
        role = canonical_reference_role(str(ref.role))
        capability = _ROLE_TO_CAPABILITY.get(role or "")
        if role is None or capability is None:
            errors.append(f"unknown reference role: {ref.role}")
            continue
        # Repeated canonical roles are meaningful multi-reference input. The
        # manifest validator owns min/max cardinality; normalization must not
        # collapse or reject them before that contract is evaluated.
        roles.add(role)
        if ref.required:
            capabilities.add(capability)
    return frozenset(capabilities), errors


def normalize_video(
    intent: VideoGenerationIntentV1,
) -> NormalizationResult:
    derived, role_errors = normalize_reference_roles(intent.references)
    capabilities = set(derived)
    errors = list(role_errors)
    if intent.output.generate_audio is True:
        capabilities.add("video.audio.generate")
    if intent.selection.mode != "explicit_binding":
        errors.append(f"selection mode not open in stage A+B: {intent.selection.mode}")
    if intent.purpose != "shot_video":
        errors.append(f"video purpose not open in stage A+B: {intent.purpose}")
    # Union caller-declared requirements; no silent narrowing.
    capabilities |= set(intent.requirements.required_capabilities)
    return NormalizationResult(
        required_capabilities=frozenset(capabilities),
        reference_roles=frozenset(ref.role for ref in intent.references),
        preferred_capabilities=frozenset(intent.preferences.preferred_capabilities),
        errors=errors,
    )


def normalize_image(
    intent: ImageGenerationIntent,
) -> NormalizationResult:
    errors: list[str] = []
    if intent.selection.mode != "explicit_binding":
        errors.append(f"selection mode not open in stage A+B: {intent.selection.mode}")
    if intent.purpose != "keyframe":
        errors.append(f"image purpose not open in stage A+B: {intent.purpose}")
    capabilities: set[str] = set(intent.requirements.required_capabilities)
    if intent.reference_artifact_id is not None:
        capabilities.add("image.i2i")
    return NormalizationResult(
        required_capabilities=frozenset(capabilities),
        reference_roles=frozenset({"reference_image"})
        if intent.reference_artifact_id is not None
        else frozenset(),
        preferred_capabilities=frozenset(intent.preferences.preferred_capabilities),
        errors=errors,
    )
