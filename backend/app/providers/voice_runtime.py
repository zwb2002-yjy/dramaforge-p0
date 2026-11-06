"""One speech runtime seam: frozen engine selection, never automatic fallback."""

from __future__ import annotations

import io
import wave
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol
from uuid import uuid4

from app.assets.voice import VoiceExecutionSpec
from app.config import get_settings
from app.providers.errors import ProviderNotConfiguredError
from app.providers.local_tts import get_local_tts_adapter
from app.providers.voice_config import EDGE_TTS_VERSION, freeze_voice_execution


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


def get_voice_adapter(spec: VoiceExecutionSpec | None = None) -> VoiceAdapter:
    settings = get_settings()
    frozen = spec or freeze_voice_execution({}, settings=settings)
    if frozen.engine == "pcm-silence":
        return SilentVoiceAdapter()
    if not settings.tts_enabled:
        raise ProviderNotConfiguredError("配音服务未启用；不会使用其他引擎代替。")
    if frozen.engine == "espeak-ng":
        if frozen.engine_version != "system-espeak-ng":
            raise ProviderNotConfiguredError("本地配音版本与冻结的执行身份不一致。")
        return get_local_tts_adapter(
            settings.model_copy(update={"tts_engine": "espeak-ng", "tts_voice": frozen.voice}),
            rate_percent=frozen.rate_percent,
        )
    try:
        installed = version("edge-tts")
    except PackageNotFoundError as exc:
        raise ProviderNotConfiguredError("Edge 配音依赖未安装；不会退回机械音。") from exc
    if installed != frozen.engine_version or installed != EDGE_TTS_VERSION:
        raise ProviderNotConfiguredError("Edge 配音版本与冻结的执行身份不一致。")
    from app.providers.edge_tts import EdgeNeuralAdapter

    return EdgeNeuralAdapter(settings, voice=frozen.voice, rate_percent=frozen.rate_percent)
