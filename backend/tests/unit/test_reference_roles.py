"""MS2 canonical reference-role and bridge tests."""

from __future__ import annotations

from uuid import uuid4

from app.providers.capabilities import Capability
from app.providers.contracts import ArtifactRef, ReferenceToVideoRequest
from app.providers.intent_bridge import video_request_to_intent
from app.providers.manifest import (
    CapabilitySpec,
    InputSlotSpec,
    OperationManifest,
    ReferenceConstraint,
)
from app.providers.reference_roles import (
    CANONICAL_REFERENCE_ROLES,
    ReferenceRole,
    canonical_reference_role,
)


def test_canonical_role_vocabulary_contains_all_five_roles() -> None:
    assert {
        "first_frame",
        "last_frame",
        "reference_image",
        "reference_video",
        "reference_audio",
    } == CANONICAL_REFERENCE_ROLES
    assert ReferenceRole.REFERENCE_IMAGE.value == "reference_image"


def test_plural_request_fields_map_to_singular_internal_roles() -> None:
    assert canonical_reference_role("reference_images") == "reference_image"
    assert canonical_reference_role("reference_videos") == "reference_video"
    assert canonical_reference_role("reference_audio") == "reference_audio"

    request = ReferenceToVideoRequest(
        prompt="p",
        reference_images=[ArtifactRef(artifact_id=str(uuid4()))],
        reference_videos=[ArtifactRef(artifact_id=str(uuid4()))],
        reference_audio=[ArtifactRef(artifact_id=str(uuid4()))],
    )
    intent = video_request_to_intent(
        Capability.VIDEO_REFERENCE_TO_VIDEO,
        request,
    )
    assert [str(reference.role) for reference in intent.references] == [
        "reference_image",
        "reference_audio",
        "reference_video",
    ]


def test_manifest_aliases_are_canonicalized_at_model_boundary() -> None:
    operation = OperationManifest(
        operation="video.generate",
        capabilities=["video.reference.image"],
        reference_constraints={
            "reference_images": ReferenceConstraint(min=1, max=4),
        },
    )
    assert set(operation.reference_constraints) == {"reference_image"}

    spec = CapabilitySpec(
        capability=Capability.VIDEO_REFERENCE_TO_VIDEO,
        input_slots={
            "reference_videos": InputSlotSpec(minimum=1, maximum=2),
        },
        transport_profile_id="t1",
    )
    assert set(spec.input_slots) == {"reference_video"}
