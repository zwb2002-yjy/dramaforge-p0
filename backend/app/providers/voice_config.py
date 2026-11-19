"""Explicit speech configuration and immutable execution identity; no network calls."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Project
from app.assets.voice import (
    ShotVoiceSettings,
    VoiceExecutionSpec,
    VoiceOptionRead,
    VoiceOptionsRead,
)
from app.config import Settings
from app.providers.errors import ProviderNotConfiguredError
from app.providers.voice_binding import VoiceBindingStatus
from app.shared.errors import ValidationAppError


def freeze_voice_execution(
    director_state: Mapping[str, object],
    *,
    settings: Settings | None = None,
    silent: bool = False,
    binding: "VoiceBindingStatus | None" = None,
) -> VoiceExecutionSpec:
    raw = director_state.get("voice") or {}
    voice = ShotVoiceSettings.model_validate(raw)
    if silent:
        return VoiceExecutionSpec(engine="pcm-silence", voice="none", engine_version="1")
    if binding is not None:
        if binding.status != "configured":
            raise ProviderNotConfiguredError(
                "项目语音模型不可用；不会自动切换到其他引擎。"
            )
        selected = voice.voice_id or binding.voice_options.get("voice_id")
        if not isinstance(selected, str) or not selected:
            raise ValidationAppError(
                "请选择该语音模型支持的音色后再生成配音。",
                details={"code": "VOICE_SELECTION_REQUIRED"},
            )
        if binding.voices and selected not in binding.voices:
            raise ValidationAppError(
                "所选音色不属于该语音模型；请显式重新选择并保存。",
                details={"code": "VOICE_UNKNOWN_FOR_BINDING"},
            )
        return VoiceExecutionSpec(
            engine="voice_model",
            voice=selected,
            rate_percent=voice.rate_percent,
            engine_version=f"voice-model:{str(binding.manifest_hash or "")[:12]}",
            binding_id=binding.binding_id,
            provider_type=binding.provider_type,
            model_id=binding.model_id,
            protocol_profile=binding.protocol_profile,
            manifest_hash=binding.manifest_hash,
        )
    raise ProviderNotConfiguredError(
        "语音必须使用项目语音模型；不会自动切换到其他引擎。"
    )


async def freeze_project_voice(
    session: AsyncSession,
    *,
    project_id: UUID,
    director_state: Mapping[str, object],
    silent: bool = False,
) -> VoiceExecutionSpec:
    """Freeze the project's voice binding into one immutable execution identity."""
    from app.providers.voice_binding import resolve_voice_binding

    project = await session.get(Project, project_id)
    if project is None:
        raise ProviderNotConfiguredError("项目不存在，无法冻结配音身份。")
    binding = await resolve_voice_binding(session, project=project)
    return freeze_voice_execution(director_state, silent=silent, binding=binding)

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
    if spec.engine == "voice_model":
        return (
            spec.provider_type or "voice_model",
            spec.model_id or spec.voice,
            f"voice-model:{str(spec.manifest_hash or "")[:12]}",
        )
    if spec.engine == "edge-tts":
        return "edge_tts", spec.voice, "edge-voice-v1"
    if spec.engine == "pcm-silence":
        return "local_audio", "pcm-silence", "silent-voice-v1"
    return "local_tts", "espeak-ng", "local-voice-v2"
