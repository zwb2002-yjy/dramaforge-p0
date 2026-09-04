"""MiniMax ``minimax_cn_v1`` mocked HTTP contract tests.

These tests cover the local adapter only. They never make a real MiniMax
request, authenticate an account, create media, or incur provider cost.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.config import Settings
from app.providers.minimax import MiniMaxHubClient

MINIMAX_HOST = "https://api.minimaxi.com"


def _settings() -> Settings:
    return Settings(
        minimax_enabled=True,
        minimax_api_key="test-minimax-key",
        minimax_base_url=MINIMAX_HOST,
    )


@pytest.mark.asyncio
async def test_image_i2i_path_auth_body_and_response() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"data": {"image_urls": ["https://cdn.example/image.png"]}},
        )

    client = MiniMaxHubClient(_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_image(
        prompt="preserve identity",
        reference_url="https://dramaforge.example/api/v1/provider-references/image-token",
        reference_artifact_id="artifact-1",
        reference_fingerprint="a" * 64,
    )

    assert seen["url"] == f"{MINIMAX_HOST}/v1/image_generation"
    assert seen["auth"] == "Bearer test-minimax-key"
    assert seen["body"] == {
        "model": "image-01",
        "prompt": "preserve identity",
        "aspect_ratio": "1:1",
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": False,
        "aigc_watermark": False,
        "subject_reference": [
            {
                "type": "character",
                "image_file": ("https://dramaforge.example/api/v1/provider-references/image-token"),
            }
        ],
    }
    assert result["status"] == "succeeded"
    assert result["artifact_uri"] == "https://cdn.example/image.png"


@pytest.mark.asyncio
async def test_video_i2v_create_poll_cancel_and_failure_state() -> None:
    seen_paths: list[tuple[str, str]] = []
    poll_responses = iter(
        [
            {"task": {"status": "queued"}},
            {"task": {"status": "running"}},
            {
                "task": {
                    "status": "succeeded",
                    "content": {"url": "https://cdn.example/video.mp4"},
                }
            },
            {"task": {"status": "failed"}},
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append((request.method, request.url.path))
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == "MiniMax-H3"
            assert body["resolution"] == "768P"
            assert body["duration"] == 5
            assert body["ratio"] == "adaptive"
            assert body["content"][1] == {
                "type": "image_url",
                "image_url": {
                    "url": "https://dramaforge.example/api/v1/provider-references/frame-token"
                },
                "role": "first_frame",
            }
            return httpx.Response(200, json={"task_id": "task-123"})
        if request.method == "DELETE":
            return httpx.Response(200, json={"status": "cancelled"})
        return httpx.Response(200, json=next(poll_responses))

    client = MiniMaxHubClient(_settings(), transport=httpx.MockTransport(handler))
    created = await client.create_video(
        prompt="slow camera move",
        image_url="https://dramaforge.example/api/v1/provider-references/frame-token",
    )
    assert created["status"] == "queued"
    assert created["remote_task_id"] == "task-123"
    assert (await client.poll_video("task-123"))["status"] == "queued"
    assert (await client.poll_video("task-123"))["status"] == "running"
    completed = await client.poll_video("task-123")
    assert completed == {
        "status": "succeeded",
        "artifact_uri": "https://cdn.example/video.mp4",
    }
    failed = await client.poll_video("task-123")
    assert failed["status"] == "failed"
    assert failed["error_code"] == "PROVIDER_TASK_FAILED"
    assert await client.cancel("task-123") == {"status": "cancelled"}
    assert seen_paths == [
        ("POST", "/v2/video_generation"),
        ("GET", "/v2/query/video_generation/task-123"),
        ("GET", "/v2/query/video_generation/task-123"),
        ("GET", "/v2/query/video_generation/task-123"),
        ("GET", "/v2/query/video_generation/task-123"),
        ("DELETE", "/v2/video_generation/task-123"),
    ]


@pytest.mark.asyncio
async def test_create_transport_failure_is_one_post_and_unknown_submission() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadError("connection lost")

    client = MiniMaxHubClient(_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_video(
        prompt="motion",
        image_url="https://dramaforge.example/frame.png",
    )
    assert calls == 1
    assert result["status"] == "unknown_submission"
    assert result["error_code"] == "PROVIDER_SUBMISSION_UNKNOWN"
    assert result["transport_error"] == "ReadError"


@pytest.mark.asyncio
async def test_missing_or_non_https_references_fail_before_network() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid references must not create a provider request")

    client = MiniMaxHubClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="HTTPS"):
        await client.create_image(prompt="portrait", reference_url="http://example.com/ref.png")
    with pytest.raises(ValueError, match="HTTPS"):
        await client.create_video(prompt="motion", image_url="data:image/png;base64,abc")


@pytest.mark.asyncio
async def test_http_error_and_summary_redaction() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "busy"})

    client = MiniMaxHubClient(_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_image(
        prompt="secret prompt",
        reference_url="https://dramaforge.example/api/v1/provider-references/secret-token",
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "PROVIDER_RATE_LIMITED"
    summary = json.dumps(result["request_summary"])
    assert "secret prompt" not in summary
    assert "secret-token" not in summary
    assert "test-minimax-key" not in summary
