"""Voice-model freeze and runtime: binding identity, one call, no fallback (I8a-02)."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from app.assets.voice import VoiceExecutionSpec
from app.providers.errors import ProviderError, ProviderNotConfiguredError
from app.providers.speech_http import SpeechProtocolError
from app.providers.speech_runtime import build_voice_model_adapter
from app.providers.voice_binding import VoiceBindingStatus
from app.providers.voice_config import freeze_voice_execution, voice_identity
from app.shared.errors import ValidationAppError

WAV = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 4
BINDING_ID = uuid4()


def _configured(**overrides) -> VoiceBindingStatus:
    values = {
        "status": "configured",
        "binding_id": BINDING_ID,
        "model_id": "voice-model",
        "provider_type": "agnes",
        "voice_options": {"voice_id": "v1"},
        "reason_code": None,
        "protocol_profile": "openai_speech_v1",
        "manifest_hash": "f" * 64,
    }
    values.update(overrides)
    return VoiceBindingStatus(**values)


def _spec(**overrides) -> VoiceExecutionSpec:
    values = {
        "engine": "voice_model",
        "voice": "v1",
        "rate_percent": 0,
        "engine_version": "voice-model:ffffffffffff",
        "binding_id": BINDING_ID,
        "provider_type": "agnes",
        "model_id": "voice-model",
        "protocol_profile": "openai_speech_v1",
        "manifest_hash": "f" * 64,
    }
    values.update(overrides)
    return VoiceExecutionSpec(**values)


def test_freeze_from_configured_binding():
    spec = freeze_voice_execution({}, binding=_configured())
    assert spec.engine == "voice_model"
    assert spec.binding_id == BINDING_ID
    assert spec.voice == "v1"
    assert spec.protocol_profile == "openai_speech_v1"
    assert voice_identity(spec) == ("agnes", "voice-model", "voice-model:ffffffffffff")
    explicit = freeze_voice_execution(
        {"voice": {"voice_id": "v2", "rate_percent": 10}}, binding=_configured()
    )
    assert explicit.voice == "v2" and explicit.rate_percent == 10


def test_freeze_refuses_missing_or_unavailable_binding():
    for status in ("missing", "unavailable"):
        with pytest.raises(ProviderNotConfiguredError):
            freeze_voice_execution({}, binding=_configured(status=status))
    with pytest.raises(ValidationAppError):
        freeze_voice_execution({}, binding=_configured(voice_options={}))


@pytest.mark.asyncio
async def test_adapter_posts_one_request_and_decodes_wav():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=WAV, headers={"content-type": "audio/wav"})

    adapter = build_voice_model_adapter(
        _spec(),
        base_url="https://speech.example",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.create({"text": "古桥始建于明代。"})
    assert result["status"] == "succeeded"
    assert adapter.blobs[result["remote_task_id"]] == WAV
    assert len(seen) == 1
    request = seen[0]
    assert request.url.path == "/v1/audio/speech"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["voice"] == "v1" and body["input"] == "古桥始建于明代。"


@pytest.mark.asyncio
async def test_adapter_decodes_json_audio_and_rejects_http_errors():
    def b64_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(
                {"data": [{"b64_json": __import__("base64").b64encode(WAV).decode()}]}
            ).encode(),
            headers={"content-type": "application/json"},
        )

    adapter = build_voice_model_adapter(
        _spec(),
        base_url="https://speech.example",
        api_key="k",
        transport=httpx.MockTransport(b64_handler),
    )
    result = await adapter.create({"text": "hello"})
    assert adapter.blobs[result["remote_task_id"]] == WAV

    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b"{}")

    failing = build_voice_model_adapter(
        _spec(),
        base_url="https://speech.example",
        api_key="k",
        transport=httpx.MockTransport(error_handler),
    )
    with pytest.raises(ProviderError):
        await failing.create({"text": "hello"})

    def not_wav(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"plain", headers={"content-type": "audio/wav"})

    malformed = build_voice_model_adapter(
        _spec(),
        base_url="https://speech.example",
        api_key="k",
        transport=httpx.MockTransport(not_wav),
    )
    with pytest.raises(SpeechProtocolError):
        await malformed.create({"text": "hello"})
