"""Volcengine Ark ``ark_cn_v1`` wire contract tests.

Locks the verified Seedream / Seedance contract: image generation is
synchronous with the reference in a top-level ``image`` array; video is an
asynchronous task with the first frame in ``content[].image_url`` plus
``role: first_frame``; polls resolve ``queued -> running -> succeeded`` and
expose the video under ``content.video_url``. Also locks fail-closed behavior:
transport ambiguity is ``unknown_submission`` and a missing video reference
fails before any request is sent.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.config import Settings
from app.providers.runtime import ProviderResumeToken
from app.providers.volcengine import ArkRuntime

from fixtures.protocol_requests import REFERENCE_ID, image_request, video_request

ARK_HOST = "https://ark.cn-beijing.volces.com/api/v3"


def _ark_settings() -> Settings:
    return Settings(
        app_env="development",
        volcengine_enabled=True,
        volcengine_api_key="test-ark-key",
        volcengine_base_url=ARK_HOST,
    )


@pytest.mark.asyncio
async def test_ark_image_t2i_path_and_body() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "data": [{"url": "https://tos.example.com/a.png"}],
                "usage": {"generated_images": 1},
            },
        )

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    result = await client.submit_image(
        await image_request("volcengine", prompt="cinematic portrait")
    )

    assert seen["url"] == f"{ARK_HOST}/images/generations"
    assert seen["auth"] == "Bearer test-ark-key"
    body = dict(seen["body"])
    assert body["model"] == "doubao-seedream-4-0-250828"
    assert body["prompt"] == "cinematic portrait"
    assert body["size"] == "2048x2048"
    assert body["response_format"] == "url"
    assert body["watermark"] is False
    assert "image" not in body  # T2I sends no reference array
    assert result.status == "succeeded"
    assert result.artifact_uri == "https://tos.example.com/a.png"
    assert result.resume_token.protocol_profile == "ark_cn_v1"
    assert client.provider == "volcengine"


@pytest.mark.asyncio
async def test_ark_image_i2i_puts_reference_in_top_level_image_array() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"data": [{"url": "https://tos.example.com/out.png"}]},
        )

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    result = await client.submit_image(
        await image_request(
            "volcengine",
            prompt="keep identity",
            reference_url="https://example.com/api/v1/provider-references/tok",
        )
    )

    body = dict(seen["body"])
    assert body["image"] == ["https://example.com/api/v1/provider-references/tok"]
    summary = result.request_summary
    assert isinstance(summary, dict)
    assert summary["operation"] == "image.i2i"
    assert summary["reference_fingerprints"] == ["a" * 64]
    assert summary["reference_artifact_ids"] == [str(REFERENCE_ID)]


@pytest.mark.asyncio
async def test_ark_image_create_transport_error_is_unknown_submission() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection lost")

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    result = await client.submit_image(await image_request("volcengine", prompt="cinematic"))
    assert result.status == "unknown_submission"
    assert result.error_code == "PROVIDER_SUBMISSION_UNKNOWN"
    assert result.error == "ReadError"
    assert client.provider == "volcengine"


@pytest.mark.asyncio
async def test_ark_video_create_uses_content_first_frame_role() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "cgt-20250807-abc123"})

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    result = await client.submit_video(
        await video_request(
            "volcengine",
            prompt="slow camera move",
            reference_url="https://example.com/api/v1/provider-references/kf-tok",
        )
    )

    body = dict(seen["body"])
    assert body["model"] == "doubao-seedance-2-0-260128"
    content = body["content"]
    assert isinstance(content, list) and len(content) == 2
    assert content[0] == {"type": "text", "text": "slow camera move"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/api/v1/provider-references/kf-tok"},
        "role": "first_frame",
    }
    assert result.status == "queued"
    assert result.remote_task_id == "cgt-20250807-abc123"
    assert result.resume_token.protocol_profile == "ark_cn_v1"


@pytest.mark.asyncio
async def test_ark_video_without_reference_fails_before_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent without a first-frame reference")

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        await client.submit_video(await video_request("volcengine", prompt="motion"))


@pytest.mark.asyncio
async def test_ark_video_transport_error_is_unknown_submission() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("tcp failed")

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    result = await client.submit_video(
        await video_request(
            "volcengine", prompt="motion", reference_url="https://example.com/ref.png"
        )
    )
    assert result.status == "unknown_submission"
    assert result.error == "ConnectError"


@pytest.mark.asyncio
async def test_ark_video_poll_state_machine_and_result_url() -> None:
    """queued -> running -> succeeded with content.video_url on completion."""
    responses = [
        {"id": "cgt-1", "status": "queued"},
        {"id": "cgt-1", "status": "running"},
        {
            "id": "cgt-1",
            "status": "succeeded",
            "content": {"video_url": "https://tos.example.com/v.mp4"},
        },
    ]
    index = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal index
        assert request.url.path == "/api/v3/contents/generations/tasks/cgt-1"
        response = responses[index]
        index += 1
        return httpx.Response(200, json=response)

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    assert (
        await client.poll_video(
            ProviderResumeToken(
                provider_type="volcengine", protocol_profile="ark_cn_v1", remote_task_id="cgt-1"
            )
        )
    ).status == "queued"
    assert (
        await client.poll_video(
            ProviderResumeToken(
                provider_type="volcengine", protocol_profile="ark_cn_v1", remote_task_id="cgt-1"
            )
        )
    ).status == "running"
    done = await client.poll_video(
        ProviderResumeToken(
            provider_type="volcengine", protocol_profile="ark_cn_v1", remote_task_id="cgt-1"
        )
    )
    assert done.status == "succeeded"
    assert done.artifact_uri == "https://tos.example.com/v.mp4"


@pytest.mark.asyncio
async def test_ark_video_poll_5xx_stays_alive_on_same_task() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "overloaded"})

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    result = await client.poll_video(
        ProviderResumeToken(
            provider_type="volcengine", protocol_profile="ark_cn_v1", remote_task_id="cgt-1"
        )
    )
    assert result.status == "running"
    assert result.error_code == "PROVIDER_POLL_TRANSIENT"


@pytest.mark.asyncio
async def test_ark_request_summary_redacts_reference_and_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "cgt-redacted"})

    client = ArkRuntime(settings=_ark_settings(), transport=httpx.MockTransport(handler))
    result = await client.submit_video(
        await video_request(
            "volcengine",
            prompt="secret prompt text",
            reference_url="https://example.com/api/v1/provider-references/secret-token",
        )
    )
    summary = result.request_summary
    assert isinstance(summary, dict)
    raw = json.dumps(summary)
    assert "secret-token" not in raw
    assert "secret prompt" not in raw
    assert "test-ark-key" not in raw
    assert result.request_fingerprint
    assert isinstance(result.request_fingerprint, str)
    assert len(result.request_fingerprint) == 64


@pytest.mark.asyncio
async def test_ark_client_unconfigured_raises() -> None:
    client = ArkRuntime(
        settings=Settings(app_env="development", volcengine_enabled=False, volcengine_api_key=""),
    )
    assert client._configured() is False
    with pytest.raises(RuntimeError):
        await client.submit_image(await image_request("volcengine", prompt="cinematic"))
    with pytest.raises(RuntimeError):
        await client.submit_video(
            await video_request(
                "volcengine", prompt="motion", reference_url="https://example.com/ref.png"
            )
        )
