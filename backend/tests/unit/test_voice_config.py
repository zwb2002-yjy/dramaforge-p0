"""Speech choices are read-only, explicit, and immutable at dispatch."""

from __future__ import annotations

import io
import wave
from uuid import uuid4

import pytest
from app.assets.voice import ShotVoiceSettings
from app.providers.errors import ProviderNotConfiguredError
from app.providers.voice_binding import VoiceBindingStatus
from app.providers.voice_config import freeze_voice_execution, voice_identity
from app.providers.voice_runtime import get_voice_adapter
from pydantic import ValidationError

BINDING_ID = uuid4()


def _binding(**overrides: object) -> VoiceBindingStatus:
    values = {
        "status": "configured",
        "binding_id": BINDING_ID,
        "model_id": "voice-model",
        "provider_type": "agnes",
        "voice_options": {"voice_id": "v1"},
        "reason_code": None,
        "protocol_profile": "openai_speech_v1",
        "manifest_hash": "a" * 64,
    }
    values.update(overrides)
    return VoiceBindingStatus(**values)


def test_binding_default_and_user_voice_have_distinct_frozen_identity() -> None:
    default = freeze_voice_execution({}, binding=_binding())
    custom = freeze_voice_execution(
        {"voice": {"voice_id": "v2", "rate_percent": -10}}, binding=_binding()
    )
    assert default.engine == "voice_model"
    assert default.voice == "v1"
    assert custom.voice == "v2"
    assert custom.rate_percent == -10
    assert custom != default
    assert voice_identity(custom) == ("agnes", "voice-model", "voice-model:aaaaaaaaaaaa")


def test_missing_binding_never_silently_falls_back() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        freeze_voice_execution({}, binding=_binding(status="missing"))
    with pytest.raises(ProviderNotConfiguredError):
        freeze_voice_execution({}, binding=_binding(status="unavailable"))


@pytest.mark.parametrize("rate", [-31, 31])
def test_voice_rate_is_bounded(rate: int) -> None:
    with pytest.raises(ValidationError):
        ShotVoiceSettings(rate_percent=rate)


@pytest.mark.asyncio
async def test_legacy_engines_are_read_only_and_never_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.assets.voice import VoiceExecutionSpec

    legacy = VoiceExecutionSpec(engine="edge-tts", voice="v", engine_version="7.2.8")
    with pytest.raises(ProviderNotConfiguredError):
        await get_voice_adapter(legacy)
    silence = VoiceExecutionSpec(engine="pcm-silence", voice="none", engine_version="1")
    adapter = await get_voice_adapter(silence)
    result = await adapter.create({"prompt": ""})
    data = adapter.blobs[result["remote_task_id"]]
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 6000
        assert not any(wav.readframes(wav.getnframes()))
    assert voice_identity(silence) == ("local_audio", "pcm-silence", "silent-voice-v1")
