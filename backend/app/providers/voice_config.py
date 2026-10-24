"""Explicit speech configuration and immutable execution identity; no network calls."""

from collections.abc import Mapping
from typing import Literal

from app.assets.voice import (
    ShotVoiceSettings,
    VoiceExecutionSpec,
    VoiceOptionRead,
    VoiceOptionsRead,
)
from app.config import Settings, get_settings
from app.shared.errors import ValidationAppError

EDGE_TTS_VERSION = "7.2.8"
EDGE_VOICES = (
    VoiceOptionRead(id="zh-CN-XiaoxiaoNeural", label="晓晓 · 普通话女声", locale="zh-CN"),
    VoiceOptionRead(id="zh-CN-YunxiNeural", label="云希 · 普通话男声", locale="zh-CN"),
)
LEGACY_VOICES = (
    VoiceOptionRead(id="cmn", label="普通话 · 本地机械音（旧版）", locale="zh-CN"),
    VoiceOptionRead(id="zh", label="普通话 · 旧版 zh 标识", locale="zh-CN"),
    VoiceOptionRead(id="en", label="英语 · 本地机械音（旧版）", locale="en"),
)


def freeze_voice_execution(
    director_state: Mapping[str, object],
    *,
    settings: Settings | None = None,
    silent: bool = False,
) -> VoiceExecutionSpec:
    config = settings or get_settings()
    raw = director_state.get("voice") or {}
    voice = ShotVoiceSettings.model_validate(raw)
    if silent:
        return VoiceExecutionSpec(engine="pcm-silence", voice="none", engine_version="1")
    selected = voice.voice_id or config.tts_voice
    if config.tts_engine == "edge-tts":
        allowed = {entry.id for entry in EDGE_VOICES}
        version = EDGE_TTS_VERSION
    elif config.tts_engine == "espeak-ng":
        allowed = {entry.id for entry in LEGACY_VOICES}
        version = "system-espeak-ng"
    else:
        raise ValidationAppError("配音引擎未正确配置；不会自动切换其他引擎。")
    if selected not in allowed:
        raise ValidationAppError("所选音色不属于当前配音引擎；请显式重新选择并保存。")
    return VoiceExecutionSpec(
        engine="edge-tts" if config.tts_engine == "edge-tts" else "espeak-ng",
        voice=selected,
        rate_percent=voice.rate_percent,
        engine_version=version,
    )


def voice_options(settings: Settings | None = None) -> VoiceOptionsRead:
    config = settings or get_settings()
    network = config.tts_engine == "edge-tts"
    entries = EDGE_VOICES if network else LEGACY_VOICES if config.tts_engine == "espeak-ng" else ()
    status: Literal["configured", "disabled", "invalid"] = (
        "configured" if config.tts_enabled else "disabled"
    )
    try:
        freeze_voice_execution({}, settings=config)
    except ValidationAppError:
        status = "invalid"
    notice = (
        "Edge 神经配音是非官方联网服务：对白发送至微软，不使用付费 Key，"
        "不保证可用性或商业使用许可。此处只读取配置，尚未联网验证；失败不会退回机械音。"
        if network
        else "本地 eSpeak 旧版机械音，无网络调用；仅保留显式选择，不作为自动回退。"
    )
    if status == "disabled":
        notice = "配音服务未启用。" + notice
    elif status == "invalid":
        notice = "配音引擎或默认音色配置不匹配，请修正配置后再生成。" + notice
    return VoiceOptionsRead(
        engine=config.tts_engine,
        enabled=config.tts_enabled,
        status=status,
        default_voice=config.tts_voice,
        network=network,
        service_notice=notice,
        voices=list(entries),
    )


def voice_identity(spec: VoiceExecutionSpec) -> tuple[str, str, str]:
    if spec.engine == "edge-tts":
        return "edge_tts", spec.voice, "edge-voice-v1"
    if spec.engine == "pcm-silence":
        return "local_audio", "pcm-silence", "silent-voice-v1"
    return "local_tts", "espeak-ng", "local-voice-v2"
