"""Text capability request contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TextGenerateRequest(BaseModel):
    """Text generation (``text.generate``)."""

    prompt: str
    max_tokens: int | None = None
    system: str | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)


class TTSRequest(BaseModel):
    """Text-to-speech (``audio.tts``)."""

    text: str
    voice: str | None = None
    language: str | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)
