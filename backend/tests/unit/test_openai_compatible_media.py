"""Tests for the protocol-level OpenAI-compatible media adapter."""

from __future__ import annotations

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
from app.providers.openai_compatible_media import (
    OPENAI_MEDIA_PROFILE,
    OpenAICompatibleImageCompiler,
    OpenAICompatibleMediaClient,
    OpenAICompatibleMediaRuntime,
    OpenAICompatibleVideoCompiler,
)
from app.providers.runtime import (
    CompiledImageRequest,
    CompiledVideoRequest,
    ResolvedReference,
)


def _settings() -> Settings:
    return Settings(
        openai_compatible_media_enabled=True,
        openai_compatible_media_api_key="test-key",
        openai_compatible_media_base_url="https://example.test/v1",
        openai_compatible_media_image_model="image-model",
        openai_compatible_media_video_model="video-model",
    )


def _manifest(model_id: str) -> ModelCapabilityManifest:
    raw = next(item for item in SEED_MANIFESTS if item["model_id"] == model_id)
    return ModelCapabilityManifest.model_validate(raw)


@pytest.mark.asyncio
async def test_protocol_client_uses_openai_compatible_image_and_video_shapes() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST" and request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"url": "https://cdn.example/image.png"}]},
            )
        if request.method == "POST" and request.url.path == "/v1/videos":
            return httpx.Response(202, json={"id": "vid-1", "status": "queued"})
        if request.method == "GET" and request.url.path == "/v1/videos/vid-1":
            return httpx.Response(
                200,
                json={"id": "vid-1", "status": "completed", "output_url": "https://cdn.example/video.mp4"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = OpenAICompatibleMediaClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    image = await client.create_image(prompt="portrait")
    video = await client.create_video(
        prompt="subtle motion", image_bytes=b"png", image_mime="image/png"
    )
    poll = await client.poll_video("vid-1")

    assert image["status"] == "succeeded"
    assert video["remote_task_id"] == "vid-1"
    assert poll["status"] == "succeeded"
    assert poll["artifact_uri"] == "https://cdn.example/video.mp4"
    assert seen[0].headers["authorization"] == "Bearer test-key"
    assert seen[0].url.path == "/v1/images/generations"
    assert seen[1].url.path == "/v1/videos"
    assert seen[1].headers["content-type"].startswith("multipart/form-data")


@pytest.mark.asyncio
async def test_compilers_bind_discovered_model_id_not_protocol_contract_id() -> None:
    artifact_id = uuid4()
    selection = ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4())
    image_intent = ImageGenerationIntent(
        prompt="portrait",
        reference_artifact_id=artifact_id,
        reference_mime="image/png",
        selection=selection,
    )
    image_ref = ResolvedReference(
        role="reference_image",
        artifact_id=artifact_id,
        content_bytes=b"png",
        mime_type="image/png",
        fingerprint="sha256:png",
    )
    image_request = await OpenAICompatibleImageCompiler().compile(
        image_intent,
        _manifest("@contract/openai-image-v1"),
        [image_ref],
        invoke_model_value="discovered-image-model",
    )

    video_intent = VideoGenerationIntentV1(
        prompt="subtle motion",
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame")],
        selection=selection,
    )
    video_ref = ResolvedReference(
        role="first_frame",
        artifact_id=artifact_id,
        content_url="https://cdn.example/frame.png",
        mime_type="image/png",
    )
    video_request = await OpenAICompatibleVideoCompiler().compile(
        video_intent,
        _manifest("@contract/openai-video-v1"),
        [video_ref],
        invoke_model_value="discovered-video-model",
    )

    assert image_request.protocol_profile == OPENAI_MEDIA_PROFILE
    assert image_request.wire_request["model"] == "discovered-image-model"
    assert image_request.wire_request["image_b64"] == "cG5n"
    assert video_request.wire_request["model"] == "discovered-video-model"
    assert video_request.wire_request["input_image_url"] == "https://cdn.example/frame.png"


@pytest.mark.asyncio
async def test_runtime_sends_compiled_model_without_substituting_settings_default() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/edits"
        body = await request.aread()
        assert b"discovered-image-model" in body
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example/image.png"}]})

    compiler = OpenAICompatibleImageCompiler()
    artifact_id = uuid4()
    request = await compiler.compile(
        ImageGenerationIntent(
            prompt="portrait",
            reference_artifact_id=artifact_id,
            reference_mime="image/png",
            selection=ModelSelectionIntent(mode="explicit_binding", model_binding_id=uuid4()),
        ),
        _manifest("@contract/openai-image-v1"),
        [
            ResolvedReference(
                role="reference_image",
                artifact_id=artifact_id,
                content_bytes=b"png",
                mime_type="image/png",
            )
        ],
        invoke_model_value="discovered-image-model",
    )
    runtime = OpenAICompatibleMediaRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_image(request)
    assert result.status == "succeeded"
    assert result.artifact_uri == "https://cdn.example/image.png"


@pytest.mark.asyncio
async def test_runtime_marks_transport_errors_as_unknown_submission() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection lost", request=request)

    runtime = OpenAICompatibleMediaRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    image_request = CompiledImageRequest(
        provider_type="openai_compatible_media",
        protocol_profile=OPENAI_MEDIA_PROFILE,
        model_id="discovered-image-model",
        operation="image.generate",
        wire_request={"model": "discovered-image-model", "prompt": "portrait"},
        request_schema_version="1",
    )
    video_request = CompiledVideoRequest(
        provider_type="openai_compatible_media",
        protocol_profile=OPENAI_MEDIA_PROFILE,
        model_id="discovered-video-model",
        operation="video.generate",
        wire_request={"model": "discovered-video-model", "prompt": "motion"},
        request_schema_version="1",
    )

    image_result = await runtime.submit_image(image_request)
    video_result = await runtime.submit_video(video_request)

    assert image_result.status == "unknown_submission"
    assert image_result.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert image_result.error == "ConnectError"
    assert video_result.status == "unknown_submission"
    assert video_result.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert video_result.error == "ConnectError"
    assert calls == 2
