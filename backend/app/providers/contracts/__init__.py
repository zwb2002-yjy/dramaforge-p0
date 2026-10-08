"""Capability request contract exports."""

from app.providers.contracts.common import (
    ArtifactRef,
    ExecutionContext,
    GenerationStatus,
    ProviderCancelResult,
    ProviderCostResult,
    ProviderCreateResult,
    ProviderPollResult,
    ResolvedArtifact,
)
from app.providers.contracts.image import ImageEditRequest, ImageGenerateRequest
from app.providers.contracts.text import TextGenerateRequest
from app.providers.contracts.video import (
    FirstLastFrameVideoRequest,
    ImageToVideoRequest,
    LastFrameVideoRequest,
    ReferenceToVideoRequest,
    TextToVideoRequest,
)

__all__ = [
    "ArtifactRef",
    "ExecutionContext",
    "FirstLastFrameVideoRequest",
    "GenerationStatus",
    "ImageEditRequest",
    "ImageGenerateRequest",
    "ImageToVideoRequest",
    "LastFrameVideoRequest",
    "ProviderCancelResult",
    "ProviderCostResult",
    "ProviderCreateResult",
    "ProviderPollResult",
    "ReferenceToVideoRequest",
    "ResolvedArtifact",
    "TextGenerateRequest",
    "TextToVideoRequest",
]
