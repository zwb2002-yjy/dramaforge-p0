"""Text capability request contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TextMessage(BaseModel):
    """One chat message (spec §67). Business code sends a semantic message list;
    the adapter maps it to each provider's message format."""

    role: Literal["system", "user", "assistant"]
    content: str


class TextGenerateRequest(BaseModel):
    """Text generation (``text.generate``). ``prompt`` is the legacy shorthand;
    structured callers use ``messages`` + ``response_format`` (spec §67–§68).
    The provider-specific JSON/function-call differences stay inside the
    adapter — never branch on a provider here."""

    prompt: str | None = None
    messages: list[TextMessage] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system: str | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any] | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)


class TTSRequest(BaseModel):
    """Text-to-speech (``audio.tts``)."""

    text: str
    voice: str | None = None
    language: str | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)
