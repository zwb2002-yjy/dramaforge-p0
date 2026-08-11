"""Video capability request contracts (V3 spec §12).

Each capability owns a stable business contract. These are *semantic* requests:
``image`` means "the first frame" in business terms; whether a provider calls it
``image``, ``first_frame_image``, or ``content[0].image_url`` is decided by the
Adapter/Compiler at translation time. Unsupported options are handled by the
validator (strict mode), never silently dropped here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.providers.contracts.common import ArtifactRef


class _VideoCommon(BaseModel):
    """Shared video output options. Each field stays semantically stable across
    providers; the Adapter maps to provider-native naming/enum."""

    duration_seconds: float | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    seed: int | None = None


class TextToVideoRequest(_VideoCommon):
    """Video generated from text only (capability ``video.text_to_video``)."""

    prompt: str
    native_options: dict[str, Any] = Field(default_factory=dict)


class ImageToVideoRequest(_VideoCommon):
    """Video generated from a first frame (capability ``video.image_to_video``)."""

    prompt: str
    image: ArtifactRef
    native_options: dict[str, Any] = Field(default_factory=dict)


class FirstLastFrameVideoRequest(_VideoCommon):
    """Video generated between two fixed frames (``video.first_last_frame``)."""

    prompt: str
    first_frame: ArtifactRef
    last_frame: ArtifactRef
    native_options: dict[str, Any] = Field(default_factory=dict)


class ReferenceToVideoRequest(BaseModel):
    """Multi-reference video: reference images / audio / video, subject refs
    (``video.reference_to_video``). Capability is business semantics; a provider
    that routes these through its image-to-video endpoint is fine — the Adapter
    decides the endpoint."""

    prompt: str
    reference_images: list[ArtifactRef] = Field(default_factory=list)
    reference_audio: list[ArtifactRef] = Field(default_factory=list)
    reference_videos: list[ArtifactRef] = Field(default_factory=list)
    duration_seconds: float | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    seed: int | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)
