"""AgnesRuntime tests: verbatim wire submission, resume polling, sanitized token."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.execution.product_path import _unknown_submission_error_summary
from app.providers.agnes import AgnesRuntime
from app.providers.runtime import (
    CompiledImageRequest,
    CompiledVideoRequest,
    ProviderResumeToken,
)


def _settings() -> Settings:
    return Settings(
        agnes_enabled=True,
        agnes_api_key="test-agnes-key",
        agnes_base_url="https://api.agnes-ai.cn",
        agnes_image_model="agnes-image-2.1-flash",
        agnes_video_model="agnes-video-v2.0",
    )


def _compiled_video() -> CompiledVideoRequest:
    return CompiledVideoRequest(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
        operation="video.generate",
        wire_request={
            "model": "agnes-video-v2.0",
            "prompt": "rainy street",
            "num_frames": 121,
            "frame_rate": 24,
            "height": 1280,
            "width": 720,
            "image": "aGVsbG8=",
        },
        request_schema_version="2026-08-10",
        safe_request_summary={"operation": "video.i2v", "model": "agnes-video-v2.0"},
        reference_artifact_ids=[uuid4()],
        reference_fingerprints=["f" * 64],
    )


def _compiled_image() -> CompiledImageRequest:
    return CompiledImageRequest(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-image-2.1-flash",
        operation="image.generate",
        wire_request={
            "model": "agnes-image-2.1-flash",
            "prompt": "portrait",
            "size": "1024x768",
            "extra_body": {"response_format": "url"},
        },
        request_schema_version="2026-08-10",
        safe_request_summary={"operation": "image.t2i", "model": "agnes-image-2.1-flash"},
    )


@pytest.mark.asyncio
async def test_runtime_submit_image_returns_synchronous_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"url": "https://media.example/i.png"}]},
        )

    runtime = AgnesRuntime(settings=_settings(), transport=httpx.MockTransport(handler))
    result = await runtime.submit_image(_compiled_image())
    assert result.status == "succeeded"
    assert result.artifact_uri == "https://media.example/i.png"
    assert runtime._image_request_timeout_s == 300.0


@pytest.mark.asyncio
async def test_runtime_serializes_paid_creates_across_instances() -> None:
    active = 0
    max_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return httpx.Response(200, json={"data": [{"url": "https://media.example/i.png"}]})

    transport = httpx.MockTransport(handler)
    first = AgnesRuntime(settings=_settings(), transport=transport)
    second = AgnesRuntime(settings=_settings(), transport=transport)

    results = await asyncio.gather(
        first.submit_image(_compiled_image()),
        second.submit_image(_compiled_image()),
    )

    assert [result.status for result in results] == ["succeeded", "succeeded"]
    assert max_active == 1


@pytest.mark.asyncio
async def test_runtime_submit_video_sends_compiled_wire_verbatim() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"video_id": "vid-1", "task_id": "task-1", "status": "queued"},
        )

    runtime = AgnesRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    compiled = _compiled_video()
    result = await runtime.submit_video(compiled)

    assert seen["url"] == "https://api.agnes-ai.cn/v1/videos"
    assert seen["auth"] == "Bearer test-agnes-key"
    # The runtime sends the compiled wire_request verbatim — no rebuild.
    assert seen["body"] == compiled.wire_request
    assert result.status == "queued"
    assert result.remote_task_id == "vid-1"
    assert result.query_kind == "video_id"
    assert result.resume_token is not None
    assert result.resume_token.provider_type == "agnes"
    assert result.resume_token.protocol_profile == "agnes_cn_v1"
    assert result.resume_token.remote_task_id == "vid-1"
    assert result.resume_token.remote_secondary_id == "task-1"
    assert result.resume_token.query_kind == "video_id"


@pytest.mark.asyncio
async def test_runtime_poll_video_uses_query_kind() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"status": "succeeded", "url": "https://cdn.example.com/v.mp4", "progress": 1.0},
        )

    runtime = AgnesRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    resume = ProviderResumeToken(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        remote_task_id="vid-9",
        query_kind="video_id",
    )
    result = await runtime.poll_video(resume)
    assert seen["url"].startswith("https://api.agnes-ai.cn/agnesapi")
    assert "video_id=vid-9" in str(seen["url"])
    assert result.status == "succeeded"
    assert result.artifact_uri == "https://cdn.example.com/v.mp4"


@pytest.mark.asyncio
async def test_runtime_transport_error_returns_unknown_submission() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("boom")

    runtime = AgnesRuntime(
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await runtime.submit_video(_compiled_video())
    assert result.status == "unknown_submission"
    assert result.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert result.error == "ReadError"
    assert result.resume_token is None


def test_unknown_submission_summary_keeps_only_safe_transport_class() -> None:
    assert _unknown_submission_error_summary("ReadError").endswith("(transport=ReadError)")
    assert "secret" not in _unknown_submission_error_summary("ReadError: secret=value")


@pytest.mark.asyncio
async def test_resume_token_never_carries_secrets_or_wire() -> None:
    runtime = AgnesRuntime(settings=_settings())
    assert runtime._configured() is True
    # Token is a pure sanitized Pydantic model: no key, no wire body, no URL.
    token = ProviderResumeToken(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        remote_task_id="vid-1",
        query_kind="video_id",
    )
    dumped = token.model_dump()
    assert "agnes-api" not in json.dumps(dumped)
    assert "prompt" not in dumped
    assert "wire_request" not in dumped
