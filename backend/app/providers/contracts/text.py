"""Text capability request contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TextMessage(BaseModel):
    """One chat message (spec §67). Business code sends a semantic message list;
    the adapter maps it to each provider's message format."""

    role: Literal["system", "user", "assistant"]
    content: str


class TextGenerateRequest(BaseModel):
    """Text generation has one message-list contract for every caller."""

    model_config = ConfigDict(extra="forbid")

    messages: list[TextMessage] = Field(min_length=1)
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any] | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)
