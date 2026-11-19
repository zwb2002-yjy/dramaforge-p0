"""Explicit speech configuration and immutable execution identity; no network calls."""

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
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


async def voice_options_for_project(
    session: AsyncSession, *, project: Project
) -> VoiceOptionsRead:
    """Project the project's voice binding; never read the instance TTS engine."""
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.voice_binding import resolve_voice_binding

    status = await resolve_voice_binding(session, project=project)
    if status.status == "missing":
        return VoiceOptionsRead(
            status="missing",
            reason_code=status.reason_code,
            notice="项目未配置语音模型；请在项目设置中选择语音模型后再生成配音。",
        )
    if status.status == "unavailable":
        return VoiceOptionsRead(
            status="unavailable",
            binding_id=status.binding_id,
            model_id=status.model_id,
            provider_type=status.provider_type,
            reason_code=status.reason_code,
            notice="已保存的语音模型当前不可用；不会自动切换到其他引擎。",
        )

    from app.providers.models import ProviderModelBinding

    binding = (
        await session.get(ProviderModelBinding, status.binding_id)
        if status.binding_id is not None
        else None
    )
    entry = (
        await session.get(ModelCatalogEntry, binding.catalog_entry_id)
        if binding is not None and binding.catalog_entry_id is not None
        else None
    )
    schema = dict(entry.option_schema_json) if entry is not None else {}
    voices: list[VoiceOptionRead] = []
    for item in schema.get("voices") or []:
        if not isinstance(item, dict):
            continue
        voice_id = item.get("id")
        if not isinstance(voice_id, str) or not voice_id:
            continue
        voices.append(
            VoiceOptionRead(
                id=voice_id,
                label=str(item.get("label") or voice_id),
                locale=str(item.get("locale") or ""),
            )
        )
    controls = sorted(
        key for key in (schema.get("properties") or {}) if isinstance(key, str)
    )
    return VoiceOptionsRead(
        status="configured",
        binding_id=status.binding_id,
        model_id=status.model_id,
        provider_type=status.provider_type,
        default_voice=(
            str(status.voice_options.get("voice_id"))
            if status.voice_options.get("voice_id")
            else None
        ),
        voices=voices,
        supported_controls=controls,
    )

def voice_identity(spec: VoiceExecutionSpec) -> tuple[str, str, str]:
    if spec.engine == "edge-tts":
        return "edge_tts", spec.voice, "edge-voice-v1"
    if spec.engine == "pcm-silence":
        return "local_audio", "pcm-silence", "silent-voice-v1"
    return "local_tts", "espeak-ng", "local-voice-v2"
