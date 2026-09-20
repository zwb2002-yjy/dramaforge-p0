"""Voice value objects owned by the shot domain; no runtime or provider dependencies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ShotVoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str | None = Field(default=None, min_length=1, max_length=120)
    rate_percent: int = Field(default=0, ge=-30, le=30)


class VoiceExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: Literal["edge-tts", "espeak-ng", "pcm-silence"]
    voice: str = Field(min_length=1, max_length=120)
    rate_percent: int = Field(default=0, ge=-30, le=30)
    engine_version: str
    output_format: Literal["audio/wav"] = "audio/wav"


class VoiceOptionRead(BaseModel):
    id: str
    label: str
    locale: str


class VoiceOptionsRead(BaseModel):
    engine: str
    enabled: bool
    status: Literal["configured", "disabled", "invalid"]
    default_voice: str
    network: bool
    service_notice: str
    voices: list[VoiceOptionRead]
