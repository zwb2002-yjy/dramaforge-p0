"""V3 capability vocabulary and capability-level request contracts.

A :class:`Capability` is the stable business label for *what the product wants
done* (``video.image_to_video``). It is deliberately coarse and provider-neutral:
the fine-grained, model-level capability strings the A+B engine uses
(``image.t2i``, ``video.i2v.first_frame``, ...) stay the authority for capability
negotiation at the model layer (see :mod:`app.providers.manifest`). This module
is additive: no A+B code is changed by its existence.

Invariant (V3 principle 1): business code depends on :class:`Capability`, never
on a provider/model name.
"""

from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    """Stable business capabilities the product layer can request."""

    TEXT_GENERATE = "text.generate"

    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT = "image.edit"

    VIDEO_TEXT_TO_VIDEO = "video.text_to_video"
    VIDEO_IMAGE_TO_VIDEO = "video.image_to_video"
    VIDEO_FIRST_LAST_FRAME = "video.first_last_frame"
    VIDEO_REFERENCE_TO_VIDEO = "video.reference_to_video"

    AUDIO_TTS = "audio.tts"


# Map a coarse V3 capability to fine-grained capability groups the A+B model
# manifests declare. Each inner tuple is a *group*: the capability is satisfied
# when at least one group is fully declared. A single-member group is the common
# OR case; a multi-member group expresses a conjunction (e.g. first+last frame
# both required for ``video.first_last_frame``). Used by the selector/validator
# layer to bridge the two vocabularies without business code branching on models.
CAPABILITY_FINE_GRAINED: dict[Capability, tuple[tuple[str, ...], ...]] = {
    Capability.TEXT_GENERATE: (("text.generate",),),
    Capability.IMAGE_GENERATE: (("image.t2i",), ("image.i2i",)),
    Capability.IMAGE_EDIT: (("image.i2i",),),
    Capability.VIDEO_TEXT_TO_VIDEO: (("video.t2v",),),
    Capability.VIDEO_IMAGE_TO_VIDEO: (("video.i2v",), ("video.i2v.first_frame",)),
    Capability.VIDEO_FIRST_LAST_FRAME: (
        ("video.keyframes",),
        ("video.i2v.first_frame", "video.i2v.last_frame"),
    ),
    Capability.VIDEO_REFERENCE_TO_VIDEO: (
        ("video.reference.image",),
        ("video.reference.video",),
        ("video.reference.audio",),
    ),
    Capability.AUDIO_TTS: (("audio.tts",),),
}


def capability_satisfied(capability: Capability, declared: set[str]) -> bool:
    """True when a model's declared fine-grained capabilities satisfy ``capability``.

    A coarse capability is satisfied when *at least one* fine-grained group is
    fully declared. For example ``video.image_to_video`` is satisfied by
    ``video.i2v.first_frame`` alone, while ``video.first_last_frame`` requires
    either ``video.keyframes`` or *both* ``video.i2v.first_frame`` and
    ``video.i2v.last_frame``.
    """
    groups = CAPABILITY_FINE_GRAINED.get(capability)
    if not groups:
        return False
    return any(all(member in declared for member in group) for group in groups)
