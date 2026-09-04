"""Ark (Seedream/Seedance) Compiler + Runtime tests: manifest fail-closed,
verbatim wire submission, model from invoke_model_value."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.providers.catalog_seed_data import SEED_MANIFESTS
from app.providers.intents import (
    ArtifactReferenceIntent,
    ImageGenerationIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
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
