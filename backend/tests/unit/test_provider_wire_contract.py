"""Protocol declarations and compiler/runtime wire ownership; no live I/O."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from app.config import Settings
from app.providers.agnes import AgnesRuntime
from app.providers.bootstrap import LITELLM_CHAT_TRANSPORT, build_v3_registry
from app.providers.minimax import MiniMaxRuntime
from app.providers.runtime import CompiledImageRequest, CompiledVideoRequest, ProviderResumeToken
from app.providers.transport import PollSpec, TransportProfile
from app.providers.volcengine import ArkRuntime
from pydantic import ValidationError

RUNTIMES = [AgnesRuntime, ArkRuntime, MiniMaxRuntime]
PATHS = {
    "agnes": ("/v1/images/generations", "/v1/videos", "/agnesapi?video_id=remote-1"),
    "volcengine": (
        "/images/generations", "/contents/generations/tasks",
        "/contents/generations/tasks/remote-1",
    ),
    "minimax": (
        "/v1/image_generation", "/v2/video_generation", "/v2/query/video_generation/remote-1",
    ),
}


def _runtime(runtime_type: Any, handler: Any) -> Any:
    prefix = runtime_type.provider
    return runtime_type(
        settings=Settings(**{
            f"{prefix}_enabled": True,
            f"{prefix}_api_key": "runtime-only-test-key",
            f"{prefix}_image_model": "must-not-use-configured-default",
            f"{prefix}_video_model": "must-not-use-configured-default",
        }),
        host="https://provider.invalid",
        transport=httpx.MockTransport(handler),
    )


def _compiled(runtime_type: Any, kind: str) -> Any:
    request_type = CompiledImageRequest if kind == "image" else CompiledVideoRequest
    return request_type(
        provider_type=runtime_type.provider,
        protocol_profile=runtime_type.protocol_profile,
        model_id="compiler-selected-model",
        operation=f"{kind}.generate",
        wire_request={
            "model": "compiler-selected-model",
            "prompt": "compiled prompt",
            "provider_native": {"ordered": ["second", "first"], "flag": False},
        },
        request_schema_version="test-v1",
        safe_request_summary={"model": "compiler-selected-model"},
    )


@pytest.mark.parametrize("runtime_type", RUNTIMES)
@pytest.mark.parametrize("kind", ["image", "video"])
async def test_runtime_sends_compiler_body_unchanged_and_binds_credentials(
    runtime_type: Any, kind: str,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "id": "remote-1", "task_id": "remote-1", "video_id": "remote-1",
            "data": {"image_urls": ["https://media.invalid/image.png"]}
            if runtime_type is MiniMaxRuntime else [{"url": "https://media.invalid/image.png"}],
            "base_resp": {"status_code": 0},
        })

    compiled = _compiled(runtime_type, kind)
    before = compiled.model_dump(mode="json")
    result = await getattr(_runtime(runtime_type, handler), f"submit_{kind}")(compiled)
    assert result.status == ("succeeded" if kind == "image" else "queued")
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == PATHS[runtime_type.provider][kind == "video"]
    assert json.loads(seen[0].content) == compiled.wire_request
    assert seen[0].headers["Authorization"] == "Bearer runtime-only-test-key"
    assert seen[0].headers["Content-Type"] == "application/json"
    assert compiled.model_dump(mode="json") == before
    assert result.resume_token is not None
    persisted = result.resume_token.model_dump_json()
    assert "runtime-only-test-key" not in persisted
    assert "compiled prompt" not in persisted
    assert ProviderResumeToken.model_validate_json(persisted) == result.resume_token


@pytest.mark.parametrize("runtime_type", RUNTIMES)
@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("mismatch", ["provider", "profile", "operation", "model", "missing_model"])
async def test_invalid_compiled_identity_fails_before_network_without_repair(
    runtime_type: Any, kind: str, mismatch: str,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500)

    compiled = _compiled(runtime_type, kind)
    if mismatch == "provider":
        compiled.provider_type = "other-provider"
    elif mismatch == "profile":
        compiled.protocol_profile = "other-profile"
    elif mismatch == "operation":
        compiled = _compiled(runtime_type, "video" if kind == "image" else "image")
    elif mismatch == "model":
        compiled.wire_request["model"] = "silently-substituted-model"
    else:
        compiled.wire_request.pop("model")
    before = compiled.model_dump(mode="json")
    with pytest.raises(ValueError, match="compiled"):
        await getattr(_runtime(runtime_type, handler), f"submit_{kind}")(compiled)
    assert seen == []
    assert compiled.model_dump(mode="json") == before


@pytest.mark.parametrize("runtime_type", RUNTIMES)
async def test_fresh_runtime_resumes_persisted_token_with_get_only(runtime_type: Any) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "running", "base_resp": {"status_code": 0}})

    token = ProviderResumeToken(
        provider_type=runtime_type.provider,
        protocol_profile=runtime_type.protocol_profile,
        remote_task_id="remote-1",
        query_kind="video_id" if runtime_type is AgnesRuntime else None,
    )
    restored = ProviderResumeToken.model_validate_json(token.model_dump_json())
    await _runtime(runtime_type, handler).poll_video(restored)
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert str(seen[0].url) == "https://provider.invalid" + PATHS[runtime_type.provider][2]
    assert seen[0].headers["Authorization"] == "Bearer runtime-only-test-key"
    assert seen[0].content == b""
    assert restored == token


def test_active_profiles_round_trip_without_becoming_executable_or_selecting_models() -> None:
    _, registry = build_v3_registry()
    profiles = registry.list_profiles()
    assert {p.id for p in profiles} == {
        "agnes-image-v1", "agnes-video-v1", "ark-image-v1", "ark-video-v1",
        "minimax-image-v1", "minimax-video-v2", "litellm-chat-v1",
    }
    for profile in profiles:
        assert TransportProfile.model_validate_json(profile.model_dump_json()) == profile
        assert "model" not in profile.model_dump()
        assert "wire_request" not in profile.model_dump()
        assert "credential" not in profile.model_dump()
    assert registry.get("litellm-chat-v1") == LITELLM_CHAT_TRANSPORT
    assert LITELLM_CHAT_TRANSPORT.path_template == "/v1/chat/completions"
    assert LITELLM_CHAT_TRANSPORT.response_mode == "sync"
    assert LITELLM_CHAT_TRANSPORT.poll is None


def test_registered_protocol_facts_cannot_drift_through_shared_references() -> None:
    _, registry = build_v3_registry()
    profile = registry.get("ark-video-v1")
    with pytest.raises(ValidationError, match="frozen"):
        profile.id = "different-id"
    with pytest.raises(ValidationError, match="frozen"):
        profile.auth.scheme = "none"
    assert profile.poll is not None
    with pytest.raises(ValidationError, match="frozen"):
        profile.poll.path_template = "/different-poll"
    assert registry.get(profile.id) == profile
    assert registry.get_or_none("different-id") is None


def test_async_poll_declaration_requires_poll_contract() -> None:
    raw = LITELLM_CHAT_TRANSPORT.model_dump()
    raw["response_mode"] = "async_poll"
    with pytest.raises(ValidationError, match="requires a poll contract"):
        TransportProfile.model_validate(raw)


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan")])
def test_poll_interval_must_be_finite_and_positive(interval: float) -> None:
    with pytest.raises(ValidationError):
        PollSpec(method="GET", path_template="/tasks/{id}", default_interval_seconds=interval)
