"""Model-neutral messages and responses for a bounded Agent tool loop."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class AgentToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1, max_length=200, pattern=r"\S")
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")
    arguments: dict[str, JsonValue]

    @field_validator("arguments")
    @classmethod
    def finite_json_arguments(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 65536:
            raise ValueError("tool arguments exceed 64 KiB")
        return value


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(default="", max_length=32000)
    tool_calls: list[AgentToolCall] = Field(default_factory=list, max_length=12)
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
        call_ids = [call.call_id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("assistant tool call IDs must be unique")
        if (
            sum(
                len(json.dumps(call.arguments, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                for call in self.tool_calls
            )
            > 65536
        ):
            raise ValueError("assistant tool arguments exceed 64 KiB in total")
        if self.role == "assistant" and not self.content.strip() and not self.tool_calls:
            raise ValueError("assistant messages require text or tool calls")
        return self


class AgentModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=32000)
    tool_calls: list[AgentToolCall] = Field(default_factory=list, max_length=12)
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    reported_cost: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    stop_reason: str | None = Field(default=None, max_length=120)

    @field_validator("usage")
    @classmethod
    def finite_usage(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        json.dumps(value, allow_nan=False)
        return value

    @model_validator(mode="after")
    def validate_response(self) -> Self:
        AgentMessage(role="assistant", content=self.text, tool_calls=self.tool_calls)
        return self
