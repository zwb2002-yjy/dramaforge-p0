"""V3 capability request → A+B domain intent bridge (pure).

The A+B engine speaks ``ImageGenerationIntent`` / ``VideoGenerationIntentV1``.
The V3 layer speaks coarse :class:`Capability` contracts. This module converts
one into the other so a V3 :class:`ModelAdapter` can drive the existing
Compiler/Runtime path unchanged. Pure — no DB, no I/O.
"""

from __future__ import annotations

from uuid import UUID

from app.providers.capabilities import Capability
from app.providers.contracts.common import ArtifactRef
from app.providers.contracts.image import ImageGenerateRequest
from app.providers.contracts.video import (
    FirstLastFrameVideoRequest,
    ImageToVideoRequest,
    ReferenceToVideoRequest,
    TextToVideoRequest,
)
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.reference_roles import ReferenceRole


class CapabilityNotSupportedError(ValueError):
    def __init__(self, capability: str) -> None:
        super().__init__(f"no intent bridge for capability: {capability}")


def _ref(artifact: ArtifactRef, role: ReferenceRole) -> ArtifactReferenceIntent:
    try:
        artifact_id = UUID(str(artifact.artifact_id))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"artifact id must be a UUID string, got: {artifact.artifact_id!r}"
        ) from exc
    return ArtifactReferenceIntent(
        artifact_id=artifact_id,
        role=role.value,
        required=True,
    )


def _video_output(request: object) -> VideoOutputIntent:
    """Carry semantic common options into the A+B intent without rounding.

    ``VideoOutputIntent`` owns the strict enum/integer validation.  In
    particular, a fractional duration or an unknown aspect ratio is rejected
    instead of being silently altered before a provider compiler sees it.
    """
    return VideoOutputIntent.model_validate(
        {
            "duration_seconds": getattr(request, "duration_seconds", None),
            "resolution": getattr(request, "resolution", None),
            "aspect_ratio": getattr(request, "aspect_ratio", None),
            "seed": getattr(request, "seed", None),
        }
    )


def video_request_to_intent(
    capability: Capability,
    request: object,
) -> VideoGenerationIntentV1:
    """Convert a V3 video contract into the A+B video intent. The selection mode
    is explicit_binding (P0 scope); the binding is resolved by the service layer
    before submission, so none is carried here."""
    selection = ModelSelectionIntent(mode="explicit_binding")
    if isinstance(request, TextToVideoRequest):
        return VideoGenerationIntentV1(
            prompt=request.prompt,
            output=_video_output(request),
            references=[],
            selection=selection,
        )
    if isinstance(request, ImageToVideoRequest):
        return VideoGenerationIntentV1(
            prompt=request.prompt,
            output=_video_output(request),
            references=[_ref(request.image, ReferenceRole.FIRST_FRAME)],
            selection=selection,
        )
    if isinstance(request, FirstLastFrameVideoRequest):
        return VideoGenerationIntentV1(
            prompt=request.prompt,
            output=_video_output(request),
            references=[
                _ref(request.first_frame, ReferenceRole.FIRST_FRAME),
                _ref(request.last_frame, ReferenceRole.LAST_FRAME),
            ],
            selection=selection,
        )
    if isinstance(request, ReferenceToVideoRequest):
        references = [
            _ref(ref, ReferenceRole.REFERENCE_IMAGE) for ref in request.reference_images
        ] + [_ref(ref, ReferenceRole.REFERENCE_AUDIO) for ref in request.reference_audio] + [
            _ref(ref, ReferenceRole.REFERENCE_VIDEO) for ref in request.reference_videos
        ]
        return VideoGenerationIntentV1(
            prompt=request.prompt,
            output=_video_output(request),
            references=references,
            selection=selection,
        )
    raise CapabilityNotSupportedError(str(capability))


def image_request_to_intent(
    capability: Capability,
    request: object,
) -> ImageGenerationIntent:
    selection = ModelSelectionIntent(mode="explicit_binding")
    if isinstance(request, ImageGenerateRequest):
        reference = request.reference_images[0] if request.reference_images else None
        return ImageGenerationIntent(
            prompt=request.prompt,
            size=request.size,
            seed=request.seed,
            reference_artifact_id=(
                UUID(str(reference.artifact_id)) if reference is not None else None
            ),
            selection=selection,
        )
    raise CapabilityNotSupportedError(str(capability))


def request_to_intent(capability: Capability, request: object) -> object:
    """Dispatch a V3 capability contract to the A+B intent it maps to."""
    if capability in {
        Capability.VIDEO_TEXT_TO_VIDEO,
        Capability.VIDEO_IMAGE_TO_VIDEO,
        Capability.VIDEO_FIRST_LAST_FRAME,
        Capability.VIDEO_REFERENCE_TO_VIDEO,
    }:
        return video_request_to_intent(capability, request)
    if capability in {Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT}:
        return image_request_to_intent(capability, request)
    raise CapabilityNotSupportedError(str(capability))
