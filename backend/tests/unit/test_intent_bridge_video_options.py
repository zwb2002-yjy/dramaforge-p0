"""The V3-to-A+B bridge must preserve semantic video common options."""

import pytest
from app.providers.capabilities import Capability
from app.providers.contracts import (
    ArtifactRef,
    FirstLastFrameVideoRequest,
    ImageToVideoRequest,
    ReferenceToVideoRequest,
    TextToVideoRequest,
)
from app.providers.intent_bridge import video_request_to_intent

_FIRST = ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000001")
_LAST = ArtifactRef(artifact_id="00000000-0000-0000-0000-000000000002")


@pytest.mark.parametrize(
    ("capability", "video_request"),
    [
        (
            Capability.VIDEO_TEXT_TO_VIDEO,
            TextToVideoRequest(prompt="p"),
        ),
        (
            Capability.VIDEO_IMAGE_TO_VIDEO,
            ImageToVideoRequest(prompt="p", image=_FIRST),
        ),
        (
            Capability.VIDEO_FIRST_LAST_FRAME,
            FirstLastFrameVideoRequest(prompt="p", first_frame=_FIRST, last_frame=_LAST),
        ),
        (
            Capability.VIDEO_REFERENCE_TO_VIDEO,
            ReferenceToVideoRequest(prompt="p", reference_images=[_FIRST]),
        ),
    ],
)
def test_all_video_requests_preserve_common_options(capability, video_request) -> None:
    video_request = video_request.model_copy(
        update={
            "duration_seconds": 5,
            "resolution": "768P",
            "aspect_ratio": "9:16",
            "seed": 42,
        }
    )
    intent = video_request_to_intent(capability, video_request)
    assert intent.output.model_dump() == {
        "aspect_ratio": "9:16",
        "duration_seconds": 5,
        "resolution": "768P",
        "generate_audio": None,
        "seed": 42,
    }


def test_fractional_duration_is_not_silently_rounded() -> None:
    request = ImageToVideoRequest(
        prompt="p",
        image=_FIRST,
        duration_seconds=4.5,
        aspect_ratio="9:16",
    )
    with pytest.raises(ValueError):
        video_request_to_intent(Capability.VIDEO_IMAGE_TO_VIDEO, request)
