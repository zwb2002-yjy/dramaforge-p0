"""Voice-model HTTP speech adapter: three wire protocols, explicit decoding.

The adapter is transport-only: it builds one protocol request from a frozen voice
request and decodes the provider response into WAV bytes. It never picks a model,
never falls back to another engine and never retries a possibly billed call.

Protocol profiles (bound at the catalog/connection level):

* ``openai_speech_v1`` — JSON body, raw ``audio/wav`` bytes or ``b64_json``.
* ``minimax_tts_v1`` — JSON body, ``data.audio`` as hex or base64.
* ``volcengine_tts_v1`` — JSON body, ``data`` as base64.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.shared.errors import ValidationAppError


class SpeechProtocolError(ValidationAppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, details={"code": code})


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    voice_id: str
    model_id: str
    speed: float | None = None
    response_format: str = "wav"
    instructions: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SpeechWireRequest:
    path: str
    headers: dict[str, str]
    body: dict[str, object]


class SpeechProtocol(Protocol):
    name: str

    def build(self, request: SpeechRequest) -> SpeechWireRequest: ...

    def decode(self, *, content_type: str, body: bytes) -> bytes: ...


def _require_wav(data: bytes) -> bytes:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise SpeechProtocolError(
            "SPEECH_RESPONSE_NOT_WAV", "speech response is not a WAV stream"
        )
    return data


def _decode_b64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SpeechProtocolError(
            "SPEECH_RESPONSE_INVALID", "speech response is not valid base64"
        ) from exc


def _decode_hex(value: str) -> bytes:
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise SpeechProtocolError(
            "SPEECH_RESPONSE_INVALID", "speech response is not valid hex"
        ) from exc


def _json_body(body: bytes) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SpeechProtocolError(
            "SPEECH_RESPONSE_INVALID", "speech response is not JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise SpeechProtocolError(
            "SPEECH_RESPONSE_INVALID", "speech response is not a JSON object"
        )
    return parsed


class OpenAISpeechProtocol:
    """OpenAI-compatible ``/audio/speech``: raw audio or ``b64_json``."""

    name = "openai_speech_v1"

    def build(self, request: SpeechRequest) -> SpeechWireRequest:
        body: dict[str, object] = {
            "model": request.model_id,
            "input": request.text,
            "voice": request.voice_id,
            "response_format": request.response_format,
        }
        if request.speed is not None:
            body["speed"] = request.speed
        if request.instructions is not None:
            body["instructions"] = request.instructions
        return SpeechWireRequest(
            path="/v1/audio/speech",
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
            body=body,
        )

    def decode(self, *, content_type: str, body: bytes) -> bytes:
        if "json" in content_type:
            payload = _json_body(body)
            data = payload.get("data")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                encoded = data[0].get("b64_json")
                if isinstance(encoded, str):
                    return _require_wav(_decode_b64(encoded))
            raise SpeechProtocolError(
                "SPEECH_RESPONSE_INVALID", "speech JSON response has no audio payload"
            )
        return _require_wav(body)


class MiniMaxSpeechProtocol:
    """MiniMax ``t2a_v2``: ``data.audio`` hex or base64."""

    name = "minimax_tts_v1"

    def build(self, request: SpeechRequest) -> SpeechWireRequest:
        body: dict[str, object] = {
            "model": request.model_id,
            "text": request.text,
            "stream": False,
            "voice_setting": {"voice_id": request.voice_id},
            "audio_setting": {"format": request.response_format},
        }
        if request.speed is not None:
            body["voice_setting"] = {
                "voice_id": request.voice_id,
                "speed": request.speed,
            }
        return SpeechWireRequest(
            path="/v1/t2a_v2",
            headers={"Content-Type": "application/json"},
            body=body,
        )

    def decode(self, *, content_type: str, body: bytes) -> bytes:
        payload = _json_body(body)
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict) and base_resp.get("status_code") not in (0, None):
            raise SpeechProtocolError(
                "SPEECH_PROVIDER_ERROR", "speech provider rejected the request"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SpeechProtocolError(
                "SPEECH_RESPONSE_INVALID", "speech response has no data object"
            )
        audio = data.get("audio")
        if not isinstance(audio, str) or not audio:
            raise SpeechProtocolError(
                "SPEECH_RESPONSE_INVALID", "speech response has no audio payload"
            )
        try:
            decoded = _decode_hex(audio)
        except SpeechProtocolError:
            decoded = _decode_b64(audio)
        return _require_wav(decoded)


class VolcengineSpeechProtocol:
    """Volcengine TTS ``/api/v1/tts``: base64 ``data``."""

    name = "volcengine_tts_v1"

    def build(self, request: SpeechRequest) -> SpeechWireRequest:
        body: dict[str, object] = {
            "app": {
                "appid": request.extra.get("appid", ""),
                "cluster": request.extra.get("cluster", ""),
            },
            "user": {"uid": request.extra.get("uid", "dramaforge")},
            "audio": {"voice_type": request.voice_id, "encoding": request.response_format},
            "request": {"text": request.text, "operation": "query"},
        }
        if request.speed is not None:
            body["audio"] = {
                "voice_type": request.voice_id,
                "encoding": request.response_format,
                "speed_ratio": request.speed,
            }
        return SpeechWireRequest(
            path="/api/v1/tts",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            body=body,
        )

    def decode(self, *, content_type: str, body: bytes) -> bytes:
        payload = _json_body(body)
        if payload.get("code") not in (0, 3000, None):
            raise SpeechProtocolError(
                "SPEECH_PROVIDER_ERROR", "speech provider rejected the request"
            )
        data = payload.get("data")
        if not isinstance(data, str) or not data:
            raise SpeechProtocolError(
                "SPEECH_RESPONSE_INVALID", "speech response has no audio payload"
            )
        return _require_wav(_decode_b64(data))


SPEECH_PROTOCOLS: dict[str, SpeechProtocol] = {
    OpenAISpeechProtocol.name: OpenAISpeechProtocol(),
    MiniMaxSpeechProtocol.name: MiniMaxSpeechProtocol(),
    VolcengineSpeechProtocol.name: VolcengineSpeechProtocol(),
}


def speech_protocol(name: str) -> SpeechProtocol:
    protocol = SPEECH_PROTOCOLS.get(name)
    if protocol is None:
        raise SpeechProtocolError(
            "SPEECH_PROTOCOL_UNKNOWN", f"unknown speech protocol {name}"
        )
    return protocol


__all__ = [
    "MiniMaxSpeechProtocol",
    "OpenAISpeechProtocol",
    "SPEECH_PROTOCOLS",
    "SpeechProtocol",
    "SpeechProtocolError",
    "SpeechRequest",
    "SpeechWireRequest",
    "VolcengineSpeechProtocol",
    "speech_protocol",
]
