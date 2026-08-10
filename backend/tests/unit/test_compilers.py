"""Agnes Compiler tests: manifest fail-closed validation + wire compilation."""

from __future__ import annotations

import base64
from uuid import uuid4

import pytest
from app.providers.agnes import AgnesImageCompiler, AgnesVideoCompiler
from app.providers.catalog_seed_data import SEED_MANIFESTS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.runtime import ResolvedReference


def _video_manifest() -> ModelCapabilityManifest:
    raw = next(m for m in SEED_MANIFESTS if m["model_id"] == "agnes-video-v2.0")
    return ModelCapabilityManifest.model_validate(raw)


def _image_manifest() -> ModelCapabilityManifest:
    raw = next(m for m in SEED_MANIFESTS if m["model_id"] == "agnes-image-2.1-flash")
    return ModelCapabilityManifest.model_validate(raw)


def _video_intent(*frame_ids: object) -> VideoGenerationIntentV1:
    references = [
        ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame")
        for frame_id in frame_ids
    ]
    return VideoGenerationIntentV1(
        prompt="rainy street",
        references=references,
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )


def test_video_compiler_requires_first_frame() -> None:
    with pytest.raises(ValueError, match="first_frame"):
        AgnesVideoCompiler().validate(_video_intent(), _video_manifest())


def test_video_compiler_rejects_too_many_first_frames() -> None:
    intent = _video_intent(uuid4(), uuid4())
    with pytest.raises(ValueError, match="too many first_frame"):
        AgnesVideoCompiler().validate(intent, _video_manifest())


@pytest.mark.asyncio
async def test_video_compiler_compiles_wire_request_with_invoke_model_value() -> None:
    frame_id = uuid4()
    frame_bytes = b"\x89PNG\r\n\x1a\nfake-png"
    resolved = ResolvedReference(
        role="first_frame",
        artifact_id=frame_id,
        content_bytes=frame_bytes,
        mime_type="image/png",
        fingerprint="f" * 64,
    )
    compiled = await AgnesVideoCompiler().compile(
        _video_intent(frame_id),
        _video_manifest(),
        [resolved],
        invoke_model_value="agnes-video-v2.0",
    )
    assert compiled.model_id == "agnes-video-v2.0"
    assert compiled.wire_request["model"] == "agnes-video-v2.0"
    assert compiled.wire_request["prompt"] == "rainy street"
    assert compiled.wire_request["num_frames"] == 121
    assert compiled.wire_request["height"] == 1280
    assert compiled.wire_request["width"] == 720
    expected_b64 = base64.b64encode(frame_bytes).decode("ascii")
    assert compiled.wire_request["image"] == expected_b64
    assert compiled.reference_artifact_ids == [frame_id]
    assert compiled.reference_fingerprints == ["f" * 64]
    assert compiled.operation == "video.generate"


def test_image_compiler_validate_rejects_unsupported_operation() -> None:
    intent = ImageGenerationIntent(
        prompt="p",
        reference_artifact_id=None,
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="image.generate"):
        AgnesImageCompiler().validate(intent, _video_manifest())


@pytest.mark.asyncio
async def test_image_compiler_compiles_t2i_wire_request() -> None:
    intent = ImageGenerationIntent(
        prompt="portrait",
        reference_artifact_id=None,
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    compiled = await AgnesImageCompiler().compile(
        intent,
        _image_manifest(),
        [],
        invoke_model_value="agnes-image-2.1-flash",
    )
    assert compiled.wire_request["model"] == "agnes-image-2.1-flash"
    assert compiled.wire_request["prompt"] == "portrait"
    assert compiled.wire_request["extra_body"]["response_format"] == "url"
    assert compiled.reference_artifact_ids == []
