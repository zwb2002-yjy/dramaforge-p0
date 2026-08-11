"""Image capability request contracts (V3 spec §12 spirit, additive)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.providers.contracts.common import ArtifactRef


class ImageGenerateRequest(BaseModel):
    """Image generation (``image.generate``). A reference image makes it
    image-to-image at the business layer; the Adapter decides the wire form."""

    prompt: str
    reference_images: list[ArtifactRef] = Field(default_factory=list)
    size: str | None = None
    seed: int | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)


class ImageEditRequest(BaseModel):
    """Image editing (``image.edit``)."""

    prompt: str
    image: ArtifactRef
    native_options: dict[str, Any] = Field(default_factory=dict)
