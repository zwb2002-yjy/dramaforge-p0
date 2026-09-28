"""Ark (Seedream/Seedance) Compiler + Runtime tests: manifest fail-closed,
verbatim wire submission, model from invoke_model_value."""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.providers.capability_resolver import ProductCapabilityPolicy
from app.providers.catalog_seed_data import SEED_MANIFESTS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.runtime import CompiledVideoRequest, ProviderResumeToken, ResolvedReference
from app.providers.volcengine import ArkImageCompiler, ArkRuntime, ArkVideoCompiler


def _video_manifest() -> ModelCapabilityManifest:
    raw = next(m for m in SEED_MANIFESTS if m["model_id"] == "doubao-seedance-1-0-pro-250528")
    return ModelCapabilityManifest.model_validate(raw)


def _image_manifest() -> ModelCapabilityManifest:
    raw = next(m for m in SEED_MANIFESTS if m["model_id"] == "doubao-seedream-4-0-250828")
    return ModelCapabilityManifest.model_validate(raw)


def _contract_video_manifest() -> ModelCapabilityManifest:
    raw = deepcopy(
        next(m for m in SEED_MANIFESTS if m["model_id"] == "doubao-seedance-2-0-260128")
    )
    raw["model_revision"] = "protocol-contract-test"
    operation = raw["operations"]["video.generate"]
    operation["input_contracts"] = {
        "frame": {
            "input_slots": {
                "first_frame": {"minimum": 1, "maximum": 1, "media_types": ["image/*"]},
                "last_frame": {"maximum": 1, "media_types": ["image/*"]},
            },
            "minimum_total_references": 1,
        },
        "reference": {
            "input_slots": {
                "reference_image": {"maximum": 9, "media_types": ["image/*"]},
                "reference_video": {"maximum": 3, "media_types": ["video/*"]},
                "reference_audio": {"maximum": 3, "media_types": ["audio/*"]},
            },
            "minimum_total_references": 1,
        },
    }
    operation["output_options"] = {
        "aspect_ratio": {
            "type": "string",
            "enum": ["adaptive", "9:16", "16:9"],
            "default": "adaptive",
        },
        "duration_seconds": {"type": "integer", "minimum": 4, "maximum": 15, "default": 5},
        "resolution": {"type": "string", "enum": ["720p", "1080p"], "default": "720p"},
        "generate_audio": {"type": "boolean", "default": False},
    }
    return ModelCapabilityManifest.model_validate(raw)


def _video_intent(frame_id: object) -> VideoGenerationIntentV1:
    return VideoGenerationIntentV1(
        prompt="rainy street",
        references=[ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )


def _settings() -> Settings:
    return Settings(
        volcengine_enabled=True,
        volcengine_api_key="test-ark-key",
        volcengine_base_url="https://ark.cn-beijing.volces.com/api/v3",
        volcengine_image_model="doubao-seedream-4-0-250828",
        volcengine_video_model="doubao-seedance-1-0-pro-250528",
    )


@pytest.mark.asyncio
async def test_ark_video_compiler_uses_invoke_model_value_and_first_frame() -> None:
    frame_id = uuid4()
    resolved = ResolvedReference(
        role="first_frame",
        artifact_id=frame_id,
        content_url="https://dramaforge.example/api/v1/provider-references/tok",
        fingerprint="c" * 64,
    )
    compiled = await ArkVideoCompiler().compile(
        _video_intent(frame_id),
        _video_manifest(),
        [resolved],
        invoke_model_value="doubao-seedance-1-0-pro-250528",
    )
    assert compiled.wire_request["model"] == "doubao-seedance-1-0-pro-250528"
    content = compiled.wire_request["content"]
    assert isinstance(content, list) and len(content) == 2
    assert content[1]["type"] == "image_url"
    assert content[1]["role"] == "first_frame"
    assert content[1]["image_url"]["url"] == "https://dramaforge.example/api/v1/provider-references/tok"
    assert compiled.reference_artifact_ids == [frame_id]


@pytest.mark.asyncio
async def test_ark_video_compiler_requires_first_frame() -> None:
    intent = VideoGenerationIntentV1(
        prompt="p",
        references=[],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="first_frame"):
        ArkVideoCompiler().validate(intent, _video_manifest())


@pytest.mark.asyncio
async def test_ark_video_contract_compiles_frame_and_mixed_references() -> None:
    compiler = ArkVideoCompiler()
    manifest = _contract_video_manifest()
    frame_id = uuid4()
    frame_intent = VideoGenerationIntentV1(
        prompt="rainy street",
        output=VideoOutputIntent(aspect_ratio="9:16", duration_seconds=6),
        references=[ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    frame = ResolvedReference(
        role="first_frame", artifact_id=frame_id, content_url="https://example.com/frame.png"
    )
    with pytest.raises(ValueError, match="explicit product policy"):
        await compiler.compile(
            frame_intent, manifest, [frame], invoke_model_value=manifest.model_id
        )
    compiled_frame = await compiler.compile(
        frame_intent,
        manifest,
        [frame],
        invoke_model_value=manifest.model_id,
        policy=ProductCapabilityPolicy(allowed_contracts=frozenset({"frame"})),
    )
    assert compiled_frame.wire_request["ratio"] == "adaptive"
    assert compiled_frame.wire_request["duration"] == 6
    assert compiled_frame.safe_request_summary["matched_contract"] == "frame"

    image_id, video_id, audio_id = uuid4(), uuid4(), uuid4()
    mixed_intent = VideoGenerationIntentV1(
        prompt="motion",
        references=[
            ArtifactReferenceIntent(artifact_id=image_id, role="reference_image"),
            ArtifactReferenceIntent(artifact_id=video_id, role="reference_video"),
            ArtifactReferenceIntent(artifact_id=audio_id, role="reference_audio"),
        ],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    mixed_references = [
        ResolvedReference(
            role="reference_image",
            artifact_id=image_id,
            mime_type="image/png",
            content_url="https://example.com/image.png",
        ),
        ResolvedReference(
            role="reference_video",
            artifact_id=video_id,
            mime_type="video/mp4",
            content_url="https://example.com/video.mp4",
        ),
        ResolvedReference(
            role="reference_audio",
            artifact_id=audio_id,
            mime_type="audio/mpeg",
            content_url="https://example.com/audio.mp3",
        ),
    ]
    with pytest.raises(ValueError, match="product policy does not open reference"):
        await compiler.compile(
            mixed_intent,
            manifest,
            mixed_references,
            invoke_model_value=manifest.model_id,
            policy=ProductCapabilityPolicy(allowed_contracts=frozenset({"frame"})),
        )
    compiled = await compiler.compile(
        mixed_intent,
        manifest,
        mixed_references,
        invoke_model_value=manifest.model_id,
        policy=ProductCapabilityPolicy(allowed_contracts=frozenset({"reference"})),
    )
    content = compiled.wire_request["content"]
    assert [item["role"] for item in content[1:]] == [
        "reference_image", "reference_video", "reference_audio"
    ]
    assert [item["type"] for item in content[1:]] == [
        "image_url", "video_url", "audio_url"
    ]
    assert compiled.reference_artifact_ids == [image_id, video_id, audio_id]
    assert "example.com" not in json.dumps(compiled.safe_request_summary)

    conflict = mixed_intent.model_copy(
        update={
            "references": [
                ArtifactReferenceIntent(artifact_id=frame_id, role="first_frame"),
                ArtifactReferenceIntent(artifact_id=video_id, role="reference_video"),
            ]
        }
    )
    with pytest.raises(ValueError, match="no input contract"):
        await compiler.compile(
            conflict,
            manifest,
            [frame, mixed_references[1]],
            invoke_model_value=manifest.model_id,
            policy=ProductCapabilityPolicy(allowed_contracts=frozenset({"frame", "reference"})),
        )


@pytest.mark.asyncio
async def test_ark_image_compiler_t2i_wire_request() -> None:
    intent = ImageGenerationIntent(
        prompt="portrait",
        reference_artifact_id=None,
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    compiled = await ArkImageCompiler().compile(
        intent, _image_manifest(), [], invoke_model_value="doubao-seedream-4-0-250828"
    )
    assert compiled.wire_request["model"] == "doubao-seedream-4-0-250828"
    assert compiled.wire_request["watermark"] is False
    assert compiled.wire_request["response_format"] == "url"
    assert "image" not in compiled.wire_request


@pytest.mark.asyncio
async def test_ark_runtime_submits_compiled_video_verbatim() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "cgt-123", "status": "queued"})

    runtime = ArkRuntime(settings=_settings(), transport=httpx.MockTransport(handler))
    compiled = CompiledVideoRequest(
        provider_type="volcengine",
        protocol_profile="ark_cn_v1",
        model_id="doubao-seedance-1-0-pro-250528",
        operation="video.generate",
        wire_request={
            "model": "doubao-seedance-1-0-pro-250528",
            "content": [
                {"type": "text", "text": "rainy street"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://dramaforge.example/api/v1/provider-references/tok"},
                    "role": "first_frame",
                },
            ],
        },
        request_schema_version="2026-08-10",
        safe_request_summary={"operation": "video.i2v"},
        reference_artifact_ids=[uuid4()],
    )
    result = await runtime.submit_video(compiled)
    assert seen["url"] == "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
    assert seen["auth"] == "Bearer test-ark-key"
    assert seen["body"] == compiled.wire_request
    assert result.status == "queued"
    assert result.remote_task_id == "cgt-123"
    assert result.resume_token is not None
    assert result.resume_token.query_kind is None  # Ark polls by task id only


@pytest.mark.asyncio
async def test_ark_runtime_polls_by_task_id() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"status": "succeeded", "content": {"video_url": "https://tos.example.com/v.mp4"}},
        )

    runtime = ArkRuntime(settings=_settings(), transport=httpx.MockTransport(handler))
    resume = ProviderResumeToken(
        provider_type="volcengine",
        protocol_profile="ark_cn_v1",
        remote_task_id="cgt-456",
    )
    result = await runtime.poll_video(resume)
    assert seen["url"] == (
        "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/cgt-456"
    )
    assert result.status == "succeeded"
    assert result.artifact_uri == "https://tos.example.com/v.mp4"
