"""Voice value objects owned by the shot domain; no runtime or provider dependencies."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShotVoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str | None = Field(default=None, min_length=1, max_length=120)
    rate_percent: int = Field(default=0, ge=-30, le=30)


class VoiceExecutionSpec(BaseModel):
    """Frozen speech identity: a voice-model binding or a historical local engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: Literal["edge-tts", "espeak-ng", "pcm-silence", "voice_model"]
    voice: str = Field(min_length=1, max_length=120)
    rate_percent: int = Field(default=0, ge=-30, le=30)
    engine_version: str
    output_format: Literal["audio/wav"] = "audio/wav"
    binding_id: UUID | None = None
    provider_type: str | None = None
    model_id: str | None = None
    protocol_profile: str | None = None
    manifest_hash: str | None = None
    connection_revision_id: UUID | None = None
    destination_revision_id: UUID | None = None
    policy_revision_id: UUID | None = None


class VoiceOptionRead(BaseModel):
    id: str
    label: str
    locale: str


class VoiceOptionsRead(BaseModel):
    """Read-only projection of the project voice binding (never an instance engine)."""

    status: Literal["configured", "unavailable", "missing"]
    binding_id: UUID | None = None
    model_id: str | None = None
    provider_type: str | None = None
    reason_code: str | None = None
    default_voice: str | None = None
    voices: list[VoiceOptionRead] = Field(default_factory=list)
    supported_controls: list[str] = Field(default_factory=list)
    notice: str | None = None
