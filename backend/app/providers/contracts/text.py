"""Text capability request contracts."""

from __future__ import annotations

import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TextToolFunction(BaseModel):
    """Chat protocol function call; arguments are JSON on the wire."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160, pattern=r"\S")
    arguments: str = Field(max_length=65536)

    @field_validator("arguments")
    @classmethod
    def json_object_arguments(cls, value: str) -> str:
        try:
            arguments = json.loads(value)
        except RecursionError as exc:
            raise ValueError("tool arguments exceed JSON nesting limits") from exc
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be a JSON object")
        encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 65536:
            raise ValueError("tool arguments exceed 64 KiB")
        return value


class TextToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200, pattern=r"\S")
    type: Literal["function"] = "function"
    function: TextToolFunction


class TextMessage(BaseModel):
    """One chat message (spec §67). Business code sends a semantic message list;
    the adapter maps it to each provider's message format."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = ""
    tool_calls: list[TextToolCall] = Field(default_factory=list, max_length=12)
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    name: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"\S")

    @model_validator(mode="after")
    def validate_role(self) -> Self:
        if self.role == "tool":
            if not self.tool_call_id:
                raise ValueError("tool messages require tool_call_id")
        elif self.tool_call_id is not None or self.name is not None:
            raise ValueError("tool_call_id and name belong to tool messages")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("only assistant messages may contain tool_calls")
        call_ids = [call.id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("assistant tool call IDs must be unique")
        if self.content is None and not self.tool_calls:
            raise ValueError("null content requires assistant tool calls")
        if self.role == "assistant" and not (self.content or "").strip() and not self.tool_calls:
            raise ValueError("assistant messages require text or tool calls")
        return self


class TextGenerateRequest(BaseModel):
    """Text generation has one message-list contract for every caller."""

    model_config = ConfigDict(extra="forbid")

    messages: list[TextMessage] = Field(min_length=1)
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Literal["none", "auto", "required"] | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    native_options: dict[str, Any] = Field(default_factory=dict)
