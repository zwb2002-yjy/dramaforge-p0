"""Voice-model speech protocols: request shape and byte decoding (I8a-02)."""

from __future__ import annotations

import base64
import json

import pytest
from app.providers.speech_http import (
    MiniMaxSpeechProtocol,
    OpenAISpeechProtocol,
    SpeechProtocolError,
    SpeechRequest,
    VolcengineSpeechProtocol,
    speech_protocol,
)

WAV = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 4


def _request(**overrides) -> SpeechRequest:
    values = {
        "text": "古桥始建于明代。",
        "voice_id": "voice-1",
        "model_id": "voice-model",
        "speed": 1.1,
        "response_format": "wav",
    }
    values.update(overrides)
    return SpeechRequest(**values)


def test_openai_protocol_builds_and_decodes_raw_audio():
    protocol = OpenAISpeechProtocol()
    wire = protocol.build(_request())
    assert wire.path == "/v1/audio/speech"
    assert wire.body == {
        "model": "voice-model",
        "input": "古桥始建于明代。",
        "voice": "voice-1",
        "response_format": "wav",
        "speed": 1.1,
    }
    assert protocol.decode(content_type="audio/wav", body=WAV) == WAV


def test_openai_protocol_decodes_b64_json():
    payload = json.dumps({"data": [{"b64_json": base64.b64encode(WAV).decode()}]}).encode()
    assert (
        OpenAISpeechProtocol().decode(content_type="application/json", body=payload) == WAV
    )


def test_minimax_protocol_decodes_hex_and_rejects_provider_error():
    protocol = MiniMaxSpeechProtocol()
    wire = protocol.build(_request(speed=None))
    assert wire.path == "/v1/t2a_v2"
    assert wire.body["voice_setting"] == {"voice_id": "voice-1"}
    assert wire.body["audio_setting"] == {"format": "wav"}
    hex_payload = json.dumps({"data": {"audio": WAV.hex()}}).encode()
    assert protocol.decode(content_type="application/json", body=hex_payload) == WAV
    error_payload = json.dumps(
        {"base_resp": {"status_code": 1004}, "data": {}}
    ).encode()
    with pytest.raises(SpeechProtocolError) as error:
        protocol.decode(content_type="application/json", body=error_payload)
    assert error.value.details["code"] == "SPEECH_PROVIDER_ERROR"


def test_volcengine_protocol_decodes_base64_and_rejects_bad_payload():
    protocol = VolcengineSpeechProtocol()
    wire = protocol.build(_request())
    assert wire.path == "/api/v1/tts"
    assert wire.body["audio"]["speed_ratio"] == 1.1
    payload = json.dumps({"code": 3000, "data": base64.b64encode(WAV).decode()}).encode()
    assert protocol.decode(content_type="application/json", body=payload) == WAV
    with pytest.raises(SpeechProtocolError) as not_wav:
        protocol.decode(
            content_type="application/json",
            body=json.dumps({"code": 3000, "data": base64.b64encode(b"nope").decode()}).encode(),
        )
    assert not_wav.value.details["code"] == "SPEECH_RESPONSE_NOT_WAV"


def test_unknown_protocol_fails_closed():
    with pytest.raises(SpeechProtocolError) as error:
        speech_protocol("edge_tts")
    assert error.value.details["code"] == "SPEECH_PROTOCOL_UNKNOWN"
