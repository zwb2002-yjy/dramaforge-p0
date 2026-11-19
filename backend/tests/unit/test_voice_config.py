"""Speech choices are read-only, explicit, and immutable at dispatch."""

import io
import wave

import pytest
from app.assets.voice import ShotVoiceSettings
from app.config import Settings
from app.providers.errors import ProviderNotConfiguredError
from app.providers.voice_config import freeze_voice_execution, voice_identity
from app.providers.voice_runtime import get_voice_adapter
from app.shared.errors import ValidationAppError
from pydantic import ValidationError


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate({"app_env": "test", "tts_enabled": True, **overrides})


def test_edge_default_and_user_voice_have_distinct_frozen_identity() -> None:
    female = freeze_voice_execution({}, settings=_settings())
    male = freeze_voice_execution(
        {"voice": {"voice_id": "zh-CN-YunxiNeural", "rate_percent": -10}}, settings=_settings()
    )
    assert female.engine == "edge-tts"
    assert female.voice == "zh-CN-XiaoxiaoNeural"
    assert male.voice == "zh-CN-YunxiNeural"
    assert male.rate_percent == -10
    assert male != female
    assert voice_identity(male) == ("edge_tts", "zh-CN-YunxiNeural", "edge-voice-v1")


@pytest.mark.parametrize(
    "overrides",
    [
        {"tts_engine": "unknown"},
        {"tts_voice": "cmn"},
        {"tts_engine": "espeak-ng", "tts_voice": "zh-CN-XiaoxiaoNeural"},
    ],
)
def test_mismatched_engine_voice_never_silently_falls_back(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationAppError):
        freeze_voice_execution({}, settings=_settings(**overrides))


@pytest.mark.parametrize("rate", [-31, 31])
def test_voice_rate_is_bounded(rate: int) -> None:
    with pytest.raises(ValidationError):
        ShotVoiceSettings(rate_percent=rate)


@pytest.mark.asyncio
async def test_disabled_service_cannot_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = freeze_voice_execution({}, settings=_settings())
    monkeypatch.setattr(
        "app.providers.voice_runtime.get_settings", lambda: _settings(tts_enabled=False)
    )
    with pytest.raises(ProviderNotConfiguredError):
        await get_voice_adapter(spec)


@pytest.mark.asyncio
async def test_worker_keeps_frozen_voice_when_instance_default_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = freeze_voice_execution({}, settings=_settings())
    monkeypatch.setattr(
        "app.providers.voice_runtime.get_settings", lambda: _settings(tts_voice="zh-CN-YunxiNeural")
    )
    adapter = await get_voice_adapter(spec)
    assert adapter.model == "zh-CN-XiaoxiaoNeural"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_empty_dialogue_is_real_silence_without_network_or_enabled_tts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = freeze_voice_execution({}, settings=_settings(), silent=True)
    monkeypatch.setattr(
        "app.providers.voice_runtime.get_settings", lambda: _settings(tts_enabled=False)
    )
    adapter = await get_voice_adapter(spec)
    result = await adapter.create({"prompt": ""})
    data = adapter.blobs[result["remote_task_id"]]
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 6000
        assert not any(wav.readframes(wav.getnframes()))
    assert voice_identity(spec) == ("local_audio", "pcm-silence", "silent-voice-v1")
