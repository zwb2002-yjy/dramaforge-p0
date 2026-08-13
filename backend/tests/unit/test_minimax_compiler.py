"""MiniMax compiler and unified runtime tests without real provider I/O."""

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
    VideoOutputIntent,
)
from app.providers.manifest import ModelCapabilityManifest
from app.providers.minimax import MiniMaxImageCompiler, MiniMaxRuntime, MiniMaxVideoCompiler
from app.providers.runtime import CompiledVideoRequest, ProviderResumeToken, ResolvedReference


def _manifest(model_id: str) -> ModelCapabilityManifest:
    return ModelCapabilityManifest.model_validate(
        next(item for item in SEED_MANIFESTS if item["model_id"] == model_id)
    )


def _settings() -> Settings:
    return Settings(
        minimax_enabled=True,
        minimax_api_key="test-minimax-key",
        minimax_base_url="https://api.minimaxi.com",
    )


@pytest.mark.asyncio
async def test_image_compiler_requires_one_https_reference_and_builds_native_body() -> None:
    artifact_id = uuid4()
    intent = ImageGenerationIntent(
        prompt="portrait",
        reference_artifact_id=artifact_id,
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    reference = ResolvedReference(
        role="reference_image",
        artifact_id=artifact_id,
        content_url="https://dramaforge.example/api/v1/provider-references/image-token",
        fingerprint="a" * 64,
    )
    compiled = await MiniMaxImageCompiler().compile(
        intent,
        _manifest("image-01"),
        [reference],
        invoke_model_value="image-01",
    )
    assert compiled.wire_request["subject_reference"] == [
        {
            "type": "character",
            "image_file": "https://dramaforge.example/api/v1/provider-references/image-token",
        }
    ]
    assert compiled.wire_request["aspect_ratio"] == "1:1"
    assert compiled.reference_artifact_ids == [artifact_id]
    assert "image-token" not in json.dumps(compiled.safe_request_summary)


@pytest.mark.asyncio
async def test_video_compiler_rejects_unsupported_outputs_and_roles() -> None:
    artifact_id = uuid4()
    intent = VideoGenerationIntentV1(
        prompt="motion",
        output=VideoOutputIntent(duration_seconds=6),
        references=[ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame")],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    with pytest.raises(ValueError, match="768P, 5 seconds"):
        MiniMaxVideoCompiler().validate(intent, _manifest("MiniMax-H3"))

    invalid_roles = intent.model_copy(
        update={
            "output": VideoOutputIntent(),
            "references": [
                ArtifactReferenceIntent(artifact_id=artifact_id, role="first_frame"),
                ArtifactReferenceIntent(artifact_id=uuid4(), role="last_frame"),
            ],
        }
    )
    with pytest.raises(ValueError, match="no other reference roles"):
        MiniMaxVideoCompiler().validate(invalid_roles, _manifest("MiniMax-H3"))


@pytest.mark.asyncio
async def test_runtime_submits_compiled_wire_request_verbatim_and_polls_task_id() -> None:
    seen: list[tuple[str, str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, str(request.url), body))
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-456"})
        return httpx.Response(
            200,
            json={
                "task": {
                    "status": "succeeded",
                    "content": {"url": "https://cdn.example/video.mp4"},
                }
            },
        )

    compiled = CompiledVideoRequest(
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
        model_id="MiniMax-H3",
        operation="video.generate",
        wire_request={"unexpected": "exact compiled body", "nested": {"number": 1}},
        request_schema_version="2026-08-13",
        safe_request_summary={"operation": "video.i2v.first_frame"},
    )
    runtime = MiniMaxRuntime(settings=_settings(), transport=httpx.MockTransport(handler))
    submitted = await runtime.submit_video(compiled)
    assert submitted.status == "queued"
    assert submitted.remote_task_id == "task-456"
    assert seen[0] == (
        "POST",
        "https://api.minimaxi.com/v2/video_generation",
        compiled.wire_request,
    )
    assert submitted.resume_token is not None
    assert submitted.resume_token.model_dump()["opaque_state"] == {}

    polled = await runtime.poll_video(
        ProviderResumeToken(
            provider_type="minimax",
            protocol_profile="minimax_cn_v1",
            remote_task_id="task-456",
        )
    )
    assert polled.status == "succeeded"
    assert polled.artifact_uri == "https://cdn.example/video.mp4"
    assert seen[1][1] == "https://api.minimaxi.com/v2/query/video_generation/task-456"
