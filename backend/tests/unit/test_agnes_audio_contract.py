"""Compile documented Agnes audio references without opening preview models."""

from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest
from app.config import get_settings
from app.providers.agnes import AgnesRuntime, AgnesVideoCompiler
from app.providers.capability_resolver import ProductCapabilityPolicy
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.intents import (
    ArtifactReferenceIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.runtime import ResolvedReference


def _preview(model_id: str) -> ModelCapabilityManifest:
    raw = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[2:] == (model_id, "2026-09-28-candidate")
    )
    manifest = ModelCapabilityManifest.model_validate(raw)
    assert manifest.lifecycle == "preview"
    assert manifest.implementation_status == "documented"
    return manifest


def _intent(references: list[ResolvedReference]) -> VideoGenerationIntentV1:
    return VideoGenerationIntentV1(
        prompt="A fictional speaker listens to <Audio 1> beside <Picture 1>.",
        references=[
            ArtifactReferenceIntent(artifact_id=ref.artifact_id, role=ref.role)
            for ref in references
        ],
        output=VideoOutputIntent(duration_seconds=5, resolution="720P", aspect_ratio="9:16"),
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )


def _audio(index: int, *, url: str | None = None) -> ResolvedReference:
    return ResolvedReference(
        role="reference_audio",
        artifact_id=UUID(int=index),
        content_url=url or f"https://example.com/audio-{index}.wav",
        mime_type="audio/wav",
        fingerprint=str(index) * 64,
        byte_size=100,
        duration_seconds=3,
    )


POLICY = ProductCapabilityPolicy(
    allowed_contracts=frozenset({"reference"}),
    allowed_options=frozenset({"duration_seconds", "resolution", "aspect_ratio"}),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["agnes-video-2.5", "agnes-video-2.5-flash"])
async def test_audio_and_image_references_preserve_role_order_without_publishing(
    model_id: str,
) -> None:
    image = ResolvedReference(
        role="reference_image",
        artifact_id=UUID(int=9),
        content_url="https://example.com/image.png",
        mime_type="image/png",
        fingerprint="9" * 64,
        byte_size=100,
        width=736,
        height=1312,
    )
    references = [_audio(2), image, _audio(1)]
    manifest = _preview(model_id)
    compiled = await AgnesVideoCompiler().compile(
        _intent(references), manifest, references, invoke_model_value=model_id, policy=POLICY
    )
    assert compiled.wire_request == {
        "model": model_id,
        "prompt": "A fictional speaker listens to <Audio 1> beside <Picture 1>.",
        "mode": "reference",
        "seconds": "5",
        "size": "720P",
        "aspect_ratio": "9:16",
        "n": 1,
        "images": ["https://example.com/image.png"],
        "audios": ["https://example.com/audio-2.wav", "https://example.com/audio-1.wav"],
    }
    assert compiled.reference_artifact_ids == [ref.artifact_id for ref in references]
    assert compiled.reference_fingerprints == [ref.fingerprint for ref in references]
    assert compiled.safe_request_summary["matched_contract"] == "reference"
    assert "example.com" not in str(compiled.safe_request_summary)
    assert manifest.lifecycle == "preview"
    assert manifest.implementation_status == "documented"


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["agnes-video-2.5", "agnes-video-2.5-flash"])
async def test_three_audio_references_compile_to_the_official_array(model_id: str) -> None:
    references = [_audio(i) for i in (1, 2, 3)]
    compiled = await AgnesVideoCompiler().compile(
        _intent(references),
        _preview(model_id),
        references,
        invoke_model_value=model_id,
        policy=POLICY,
    )
    assert compiled.wire_request["audios"] == [ref.content_url for ref in references]
    assert "images" not in compiled.wire_request
    assert "videos" not in compiled.wire_request


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["agnes-video-2.5", "agnes-video-2.5-flash"])
async def test_four_audio_references_remain_rejected_by_the_frozen_contract(model_id: str) -> None:
    references = [_audio(i) for i in (1, 2, 3, 4)]
    with pytest.raises(ValueError, match="no input contract"):
        await AgnesVideoCompiler().compile(
            _intent(references),
            _preview(model_id),
            references,
            invoke_model_value=model_id,
            policy=POLICY,
        )


@pytest.mark.asyncio
async def test_audio_references_require_https_url_delivery() -> None:
    references = [_audio(1, url="http://example.com/audio.wav")]
    with pytest.raises(ValueError, match="public HTTPS"):
        await AgnesVideoCompiler().compile(
            _intent(references),
            _preview("agnes-video-2.5-flash"),
            references,
            invoke_model_value="agnes-video-2.5-flash",
            policy=POLICY,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_failure", [False, True])
async def test_runtime_sends_compiled_audio_once_without_rewriting_or_retrying(
    transport_failure: bool,
) -> None:
    references = [_audio(2), _audio(1)]
    compiled = await AgnesVideoCompiler().compile(
        _intent(references),
        _preview("agnes-video-2.5-flash"),
        references,
        invoke_model_value="agnes-video-2.5-flash",
        policy=POLICY,
    )
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if transport_failure:
            raise httpx.ReadTimeout("response unavailable", request=request)
        return httpx.Response(200, json={"video_id": "offline-video", "status": "queued"})

    settings = get_settings().model_copy(
        update={"agnes_enabled": True, "agnes_api_key": "unit-test-key"}
    )
    result = await AgnesRuntime(
        settings=settings,
        host="https://api.agnes-ai.cn",
        transport=httpx.MockTransport(respond),
    ).submit_video(compiled)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.agnes-ai.cn/v1/videos"
    assert request.headers["Authorization"] == "Bearer unit-test-key"
    assert json.loads(request.content) == compiled.wire_request
    assert result.status == ("unknown_submission" if transport_failure else "queued")
    assert result.remote_task_id == (None if transport_failure else "offline-video")
