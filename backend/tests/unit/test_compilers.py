"""Agnes Compiler tests: manifest fail-closed validation + wire compilation."""

from __future__ import annotations

import base64
from uuid import uuid4

import pytest
from app.providers.agnes import AgnesImageCompiler, AgnesVideoCompiler
from app.providers.capability_resolver import ProductCapabilityPolicy
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.catalog_seed_data import SEED_MANIFESTS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.runtime import ResolvedReference


def _video_manifest() -> ModelCapabilityManifest:
    raw = next(m for m in SEED_MANIFESTS if m["model_id"] == "agnes-video-v2.0")
    return ModelCapabilityManifest.model_validate(raw)


def _image_manifest() -> ModelCapabilityManifest:
    raw = next(m for m in SEED_MANIFESTS if m["model_id"] == "agnes-image-2.1-flash")
    return ModelCapabilityManifest.model_validate(raw)


def _candidate_image_manifest() -> ModelCapabilityManifest:
    raw = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[2] == "agnes-image-2.5-flash"
    )
    # Compiler fixture only: catalog publication and execution eligibility remain preview.
    raw["lifecycle"] = "active"
    raw["implementation_status"] = "contract_tested"
    return ModelCapabilityManifest.model_validate(raw)


def _candidate_video_manifest(model_id: str = "agnes-video-2.5") -> ModelCapabilityManifest:
    raw = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[2] == model_id
    )
    raw["lifecycle"] = "active"
    raw["implementation_status"] = "contract_tested"
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


@pytest.mark.parametrize(
    ("output", "message"),
    [
        (VideoOutputIntent(aspect_ratio="16:9"), "only supports 9:16"),
        (VideoOutputIntent(duration_seconds=6), "requires a 5 second"),
        (VideoOutputIntent(generate_audio=True), "cannot request native audio"),
    ],
)
def test_video_compiler_rejects_options_outside_verified_subset(
    output: VideoOutputIntent,
    message: str,
) -> None:
    frame_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="rainy street",
        output=output,
        references=[ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match=message):
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


@pytest.mark.parametrize(
    ("constraint", "value"),
    [
        ("size", "2K"),
        ("aspect_ratio", "16:9"),
        ("width", 1024),
        ("height", 1792),
    ],
)
def test_image_compiler_rejects_manifest_outside_verified_subset(
    constraint: str,
    value: object,
) -> None:
    manifest = _image_manifest().model_copy(deep=True)
    manifest.operations["image.generate"].output_constraints[constraint] = value
    intent = ImageGenerationIntent(
        prompt="portrait",
        aspect_ratio="9:16",
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )

    with pytest.raises(ValueError, match="outside the verified product subset"):
        AgnesImageCompiler().validate(intent, manifest)


def test_image_compiler_rejects_size_outside_frozen_manifest() -> None:
    intent = ImageGenerationIntent(
        prompt="portrait",
        size="1080x1920",
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="does not match frozen manifest size 1K"):
        AgnesImageCompiler().validate(intent, _image_manifest())


def test_image_compiler_rejects_ratio_outside_frozen_manifest() -> None:
    intent = ImageGenerationIntent(
        prompt="portrait",
        aspect_ratio="16:9",
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="does not match frozen manifest ratio 9:16"):
        AgnesImageCompiler().validate(intent, _image_manifest())


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
    assert compiled.wire_request["size"] == "1K"
    assert compiled.wire_request["ratio"] == "9:16"
    assert compiled.wire_request["extra_body"]["response_format"] == "url"
    assert compiled.safe_request_summary["size"] == "1K"
    assert compiled.safe_request_summary["aspect_ratio"] == "9:16"
    assert compiled.safe_request_summary["translation_transformations"] == [
        {
            "field": "size",
            "from_value": None,
            "to_value": "1K",
            "reason": "frozen_manifest_native_size_tier",
        }
    ]
    assert compiled.reference_artifact_ids == []


@pytest.mark.asyncio
async def test_agnes_image_contract_compiles_ordered_multi_reference_without_network() -> None:
    first_id, second_id = uuid4(), uuid4()
    intent = ImageGenerationIntent(
        prompt="combine portraits",
        size="2K",
        aspect_ratio="9:16",
        reference_artifact_ids=[first_id, second_id],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    references = [
        ResolvedReference(
            role="reference_image",
            artifact_id=first_id,
            content_url="https://example.com/first.png",
            mime_type="image/png",
        ),
        ResolvedReference(
            role="reference_image",
            artifact_id=second_id,
            content_bytes=b"second-image",
            mime_type="image/png",
        ),
    ]
    compiled = await AgnesImageCompiler().compile(
        intent,
        _candidate_image_manifest(),
        references,
        invoke_model_value="agnes-image-2.5-flash",
        policy=ProductCapabilityPolicy(
            allowed_contracts=frozenset({"text", "reference"}),
            allowed_options=frozenset({"size", "aspect_ratio", "response_format"}),
        ),
    )
    assert compiled.wire_request["size"] == "2K"
    assert compiled.wire_request["extra_body"]["image"][0] == "https://example.com/first.png"
    assert compiled.wire_request["extra_body"]["image"][1].startswith("data:image/png;base64,")
    assert compiled.reference_artifact_ids == [first_id, second_id]
    assert "example.com" not in str(compiled.safe_request_summary)


@pytest.mark.asyncio
async def test_agnes_image_contract_rejects_reference_bytes_fingerprint_mismatch() -> None:
    reference_id = uuid4()
    intent = ImageGenerationIntent(
        prompt="portrait",
        reference_artifact_id=reference_id,
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="bytes do not match"):
        await AgnesImageCompiler().compile(
            intent,
            _candidate_image_manifest(),
            [
                ResolvedReference(
                    role="reference_image",
                    artifact_id=reference_id,
                    content_bytes=b"image",
                    mime_type="image/png",
                    fingerprint="0" * 64,
                )
            ],
            invoke_model_value="agnes-image-2.5-flash",
            policy=ProductCapabilityPolicy(allowed_contracts=frozenset({"reference"})),
        )


@pytest.mark.asyncio
async def test_agnes_video_contract_derives_keyframe_wire_mode() -> None:
    first_id, last_id = uuid4(), uuid4()
    intent = VideoGenerationIntentV1(
        prompt="camera moves slowly",
        references=[
            ArtifactReferenceIntent(artifact_id=first_id, role="first_frame"),
            ArtifactReferenceIntent(artifact_id=last_id, role="last_frame"),
        ],
        output=VideoOutputIntent(duration_seconds=6, resolution="1080P", aspect_ratio="9:16"),
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    references = [
        ResolvedReference(role="first_frame", artifact_id=first_id, content_url="https://example.com/a.png"),
        ResolvedReference(role="last_frame", artifact_id=last_id, content_url="https://example.com/b.png"),
    ]
    compiled = await AgnesVideoCompiler().compile(
        intent,
        _candidate_video_manifest(),
        references,
        invoke_model_value="agnes-video-2.5",
        policy=ProductCapabilityPolicy(
            allowed_contracts=frozenset({"frame"}),
            allowed_options=frozenset({"duration_seconds", "resolution", "aspect_ratio"}),
        ),
    )
    assert compiled.wire_request == {
        "model": "agnes-video-2.5",
        "prompt": "camera moves slowly",
        "mode": "keyframe",
        "seconds": "6",
        "size": "1080P",
        "aspect_ratio": "9:16",
        "n": 1,
        "first_frame": "https://example.com/a.png",
        "last_frame": "https://example.com/b.png",
    }
    assert compiled.reference_artifact_ids == [first_id, last_id]
    assert "example.com" not in str(compiled.safe_request_summary)


@pytest.mark.asyncio
async def test_agnes_video_contract_rejects_unverified_audio_wire_shape() -> None:
    audio_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="rhythmic movement",
        references=[ArtifactReferenceIntent(artifact_id=audio_id, role="reference_audio")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="audio wire shape is not verified"):
        await AgnesVideoCompiler().compile(
            intent,
            _candidate_video_manifest(),
            [
                ResolvedReference(
                    role="reference_audio",
                    artifact_id=audio_id,
                    content_url="https://example.com/a.mp3",
                    mime_type="audio/mpeg",
                )
            ],
            invoke_model_value="agnes-video-2.5",
            policy=ProductCapabilityPolicy(allowed_contracts=frozenset({"reference"})),
        )


@pytest.mark.asyncio
async def test_image_compiler_rejects_missing_or_mismatched_resolved_reference() -> None:
    reference_id = uuid4()
    intent = ImageGenerationIntent(
        prompt="portrait",
        aspect_ratio="9:16",
        reference_artifact_id=reference_id,
        reference_fingerprint="a" * 64,
        reference_mime="image/png",
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )

    with pytest.raises(ValueError, match="was not resolved"):
        await AgnesImageCompiler().compile(
            intent,
            _image_manifest(),
            [],
            invoke_model_value="agnes-image-2.1-flash",
        )

    mismatched = ResolvedReference(
        role="reference_image",
        artifact_id=uuid4(),
        content_bytes=b"\x89PNG\r\n\x1a\nreference",
        mime_type="image/png",
        fingerprint="a" * 64,
    )
    with pytest.raises(ValueError, match="does not match the image intent"):
        await AgnesImageCompiler().compile(
            intent,
            _image_manifest(),
            [mismatched],
            invoke_model_value="agnes-image-2.1-flash",
        )


@pytest.mark.asyncio
async def test_video_compiler_rejects_mismatched_resolved_first_frame() -> None:
    intent_id = uuid4()
    resolved = ResolvedReference(
        role="first_frame",
        artifact_id=uuid4(),
        content_bytes=b"\x89PNG\r\n\x1a\nframe",
        mime_type="image/png",
        fingerprint="b" * 64,
    )

    with pytest.raises(ValueError, match="does not match the video intent"):
        await AgnesVideoCompiler().compile(
            _video_intent(intent_id),
            _video_manifest(),
            [resolved],
            invoke_model_value="agnes-video-v2.0",
        )
