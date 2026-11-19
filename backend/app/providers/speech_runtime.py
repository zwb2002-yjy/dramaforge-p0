"""Voice-model runtime: one HTTP speech call per NodeRun, no fallback, no retry.

The adapter is built from a frozen :class:`VoiceExecutionSpec` that names one voice
``ProviderModelBinding``. It posts exactly one protocol request and decodes the WAV
bytes; a non-2xx or malformed response fails the run instead of switching engines.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from app.assets.voice import VoiceExecutionSpec
from app.providers.errors import ProviderError, ProviderErrorCode, ProviderNotConfiguredError
from app.providers.speech_http import SpeechProtocol, SpeechRequest, speech_protocol
from app.shared.errors import ValidationAppError


class SpeechHttpAdapter:
    """One voice-model adapter bound to a base URL, key and wire protocol."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        protocol: SpeechProtocol,
        spec: VoiceExecutionSpec,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.blobs: dict[str, bytes] = {}
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._protocol = protocol
        self._spec = spec
        self._transport = transport
        self._timeout = timeout_seconds

    def _request(self, text: str) -> SpeechRequest:
        speed = 1.0 + (self._spec.rate_percent / 100.0)
        return SpeechRequest(
            text=text,
            voice_id=self._spec.voice,
            model_id=self._spec.model_id or self._spec.voice,
            speed=speed,
            response_format="wav",
        )

    async def create(self, request: dict[str, Any]) -> dict[str, Any]:
        text = request.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValidationAppError(
                "speech request needs non-empty text",
                details={"code": "SPEECH_TEXT_REQUIRED"},
            )
        wire = self._protocol.build(self._request(text))
        headers = {**wire.headers, "Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                transport=self._transport,
                timeout=self._timeout,
            ) as client:
                response = await client.post(wire.path, headers=headers, json=wire.body)
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                "speech provider is unreachable",
            ) from exc
        if response.status_code >= 400:
            raise ProviderError(
                ProviderErrorCode.INVALID_REQUEST,
                "speech provider rejected the request",
                details={"status": response.status_code},
            )
        data = self._protocol.decode(
            content_type=response.headers.get("content-type", ""),
            body=response.content,
        )
        key = f"speech-{uuid4()}"
        self.blobs[key] = data
        return {"remote_task_id": key, "status": "succeeded"}

    async def poll(self, remote_task_id: str) -> dict[str, Any]:
        return {"status": "succeeded" if remote_task_id in self.blobs else "failed"}


def build_voice_model_adapter(
    spec: VoiceExecutionSpec,
    *,
    base_url: str,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SpeechHttpAdapter:
    if spec.engine != "voice_model":
        raise ProviderNotConfiguredError("not a voice-model execution")
    protocol = speech_protocol(spec.protocol_profile or "")
    return SpeechHttpAdapter(
        base_url=base_url,
        api_key=api_key,
        protocol=protocol,
        spec=spec,
        transport=transport,
    )


__all__ = ["SpeechHttpAdapter", "build_voice_model_adapter"]
