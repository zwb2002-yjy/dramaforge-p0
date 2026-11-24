"""One speech runtime seam: a frozen voice-model binding, never a fallback engine."""

from __future__ import annotations

import io
import wave
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.voice import VoiceExecutionSpec
from app.providers.errors import ProviderNotConfiguredError


class VoiceAdapter(Protocol):
    blobs: dict[str, bytes]

    async def create(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def poll(self, remote_task_id: str) -> dict[str, Any]: ...


class SilentVoiceAdapter:
    """An empty dialogue is silence, not the spoken words 'silent paragraph'."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        target = io.BytesIO()
        with wave.open(target, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(bytes(12000))  # 250 ms; composition pads to the shot duration.
        key = f"silence-{uuid4()}"
        self.blobs[key] = target.getvalue()
        return {"remote_task_id": key, "status": "succeeded"}

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return {"status": "succeeded" if remote_task_id in self.blobs else "failed"}


async def get_voice_adapter(
    spec: VoiceExecutionSpec,
    *,
    project_id: UUID | None = None,
    session: AsyncSession | None = None,
    transport: Any = None,
) -> VoiceAdapter:
    if spec.engine == "pcm-silence":
        return SilentVoiceAdapter()
    if spec.engine == "voice_model":
        return await _voice_model_adapter(
            spec, project_id=project_id, session=session, transport=transport
        )
    raise ProviderNotConfiguredError("历史配音引擎已停用；不会自动切换到其他引擎。")


async def _voice_model_adapter(
    spec: VoiceExecutionSpec,
    *,
    project_id: UUID | None,
    session: AsyncSession | None,
    transport: Any,
) -> VoiceAdapter:
    from app.access.models import Project
    from app.providers.models import ProviderConnectionRevision
    from app.providers.speech_runtime import build_voice_model_adapter
    from app.providers.voice_binding import resolve_voice_binding
    from app.providers.workspace_credentials import configured_byok_keyring
    from app.security.credentials import read_credential_by_id

    if session is None or spec.binding_id is None:
        raise ProviderNotConfiguredError("语音模型身份缺少绑定；不会自动切换到其他引擎。")
    if project_id is None or spec.connection_revision_id is None:
        raise ProviderNotConfiguredError("语音任务缺少冻结的项目或连接修订，请重新确认。")
    project = await session.get(Project, project_id)
    if project is None:
        raise ProviderNotConfiguredError("语音项目不可用。")
    current = await resolve_voice_binding(session, project=project)
    if current.status != "configured" or (
        current.binding_id,
        current.connection_revision_id,
        current.destination_revision_id,
        current.policy_revision_id,
        current.model_id,
        current.provider_type,
        current.manifest_hash,
        current.protocol_profile,
    ) != (
        spec.binding_id,
        spec.connection_revision_id,
        spec.destination_revision_id,
        spec.policy_revision_id,
        spec.model_id,
        spec.provider_type,
        spec.manifest_hash,
        spec.protocol_profile,
    ):
        raise ProviderNotConfiguredError(current.reason_code or "VOICE_DESTINATION_CHANGED")
    revision = await session.get(ProviderConnectionRevision, spec.connection_revision_id)
    if revision is None or revision.credential_revision_id is None:
        raise ProviderNotConfiguredError("语音连接修订或凭据不可用。")
    api_key = await read_credential_by_id(
        session,
        workspace_id=project.workspace_id,
        credential_id=revision.credential_revision_id,
        keyring=configured_byok_keyring(),
    )
    if not api_key:
        raise ProviderNotConfiguredError("语音模型凭据不可用。")
    return build_voice_model_adapter(
        spec,
        base_url=revision.base_url,
        api_key=api_key,
        transport=transport,
    )
