"""One speech runtime seam: a frozen voice-model binding, never a fallback engine."""

from __future__ import annotations

import io
import wave
from typing import Any, Protocol
from uuid import uuid4

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
    session: AsyncSession | None = None,
    transport: Any = None,
) -> VoiceAdapter:
    if spec.engine == "pcm-silence":
        return SilentVoiceAdapter()
    if spec.engine == "voice_model":
        return await _voice_model_adapter(spec, session=session, transport=transport)
    raise ProviderNotConfiguredError(
        "历史配音引擎已停用；不会自动切换到其他引擎。"
    )


async def _voice_model_adapter(
    spec: VoiceExecutionSpec,
    *,
    session: AsyncSession | None,
    transport: Any,
) -> VoiceAdapter:
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.connection_service import _resolve_plugin  # noqa: F401
    from app.providers.models import ProviderConnection, ProviderModelBinding
    from app.providers.speech_runtime import build_voice_model_adapter
    from app.providers.workspace_credentials import configured_byok_keyring
    from app.security.credentials import read_credential_by_id

    if session is None or spec.binding_id is None:
        raise ProviderNotConfiguredError(
            "语音模型身份缺少绑定；不会自动切换到其他引擎。"
        )
    binding = await session.get(ProviderModelBinding, spec.binding_id)
    if binding is None or not binding.enabled:
        raise ProviderNotConfiguredError("语音模型绑定不可用。")
    connection = await session.get(ProviderConnection, binding.connection_id)
    if connection is None:
        raise ProviderNotConfiguredError("语音模型连接不可用。")
    entry = (
        await session.get(ModelCatalogEntry, binding.catalog_entry_id)
        if binding.catalog_entry_id is not None
        else None
    )
    if entry is None or entry.media_kind != "voice":
        raise ProviderNotConfiguredError("语音模型目录不可用。")
    if connection.credential_id is None:
        raise ProviderNotConfiguredError("语音模型凭据不可用。")
    api_key = await read_credential_by_id(
        session,
        workspace_id=binding.workspace_id,
        credential_id=connection.credential_id,
        keyring=configured_byok_keyring(),
    )
    if not api_key:
        raise ProviderNotConfiguredError("语音模型凭据不可用。")
    return build_voice_model_adapter(
        spec,
        base_url=connection.base_url,
        api_key=api_key,
        transport=transport,
    )
