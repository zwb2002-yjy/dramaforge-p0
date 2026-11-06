"""Typed Compiler fixtures for real Runtime transport contract assertions."""

from uuid import UUID

from app.providers.catalog_loader import CATALOG_MODELS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.minimax import MiniMaxImageCompiler, MiniMaxVideoCompiler
from app.providers.runtime import ResolvedReference
from app.providers.volcengine import ArkImageCompiler, ArkVideoCompiler

REFERENCE_ID = UUID("00000000-0000-4000-8000-000000000001")


async def image_request(provider: str, *, prompt: str, reference_url: str | None = None):
    model_id = "image-01" if provider == "minimax" else "doubao-seedream-4-0-250828"
    model = ModelCapabilityManifest.model_validate(
        next(m for m in CATALOG_MODELS if m["model_id"] == model_id)
    )
    compiler = MiniMaxImageCompiler() if provider == "minimax" else ArkImageCompiler()
    references = (
        [
            ResolvedReference(
                role="reference_image",
                artifact_id=REFERENCE_ID,
                content_url=reference_url,
                fingerprint="a" * 64,
            )
        ]
        if reference_url is not None
        else []
    )
    return await compiler.compile(
        ImageGenerationIntent(
            prompt=prompt,
            reference_artifact_ids=[REFERENCE_ID] if references else [],
            selection=ModelSelectionIntent(mode="explicit_binding"),
        ),
        model,
        references,
        invoke_model_value=model_id,
    )


async def video_request(provider: str, *, prompt: str, reference_url: str | None = None):
    model_id = "MiniMax-H3" if provider == "minimax" else "doubao-seedance-2-0-260128"
    model = ModelCapabilityManifest.model_validate(
        next(m for m in CATALOG_MODELS if m["model_id"] == model_id)
    )
    compiler = MiniMaxVideoCompiler() if provider == "minimax" else ArkVideoCompiler()
    references = (
        [
            ResolvedReference(
                role="first_frame",
                artifact_id=REFERENCE_ID,
                content_url=reference_url,
                fingerprint="a" * 64,
            )
        ]
        if reference_url is not None
        else []
    )
    return await compiler.compile(
        VideoGenerationIntentV1(
            prompt=prompt,
            references=[ArtifactReferenceIntent(artifact_id=REFERENCE_ID, role="first_frame")]
            if references
            else [],
            output=VideoOutputIntent(
                aspect_ratio="9:16", duration_seconds=5, resolution="768P", generate_audio=False
            )
            if provider == "minimax"
            else VideoOutputIntent(),
            selection=ModelSelectionIntent(mode="explicit_binding"),
        ),
        model,
        references,
        invoke_model_value=model_id,
    )
