"""Deterministic request projection without summarizing or trimming current facts.

Keep the original transcript for audit and call this projection before each
model request. Its budget covers the canonical JSON envelope of messages AND
tool definitions, not transport headers or an estimate of model tokens.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.contracts.agent import AgentMessage


class AgentContextInvalid(ValueError):
    """Unsafe conversation shape; do not submit a guessed or repaired transcript."""

    reason = "context_invalid"


class AgentContextOverflow(ValueError):
    """Required current context and tool contracts cannot fit without data loss."""

    reason = "context_limit"

    def __init__(
        self,
        *,
        required_bytes: int,
        max_bytes: int,
        omitted_history_groups: int,
    ) -> None:
        super().__init__("Required Agent context exceeds the complete request byte limit")
        self.required_bytes = required_bytes
        self.max_bytes = max_bytes
        self.omitted_history_groups = omitted_history_groups


@dataclass(frozen=True)
class AgentContext:
    """Immutable request evidence; accessors return fresh detached message/tool values.

    ``request_json`` is internal request evidence, not a public diagnostic event.
    Public/audit summaries may use only the hash, counts and byte size.
    """

    request_json: str
    request_bytes: int
    omitted_history_groups: int
    retained_history_groups: int
    context_hash: str

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        payload = json.loads(self.request_json)
        return tuple(AgentMessage.model_validate(row) for row in payload["messages"])

    @property
    def tools(self) -> tuple[dict[str, Any], ...]:
        payload = json.loads(self.request_json)
        return tuple(payload["tools"])


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise AgentContextInvalid("Agent context must contain finite JSON values") from exc


def _validate_turn(group: Sequence[AgentMessage]) -> None:
    if not group or group[0].role != "user":
        raise AgentContextInvalid("Each conversation group must begin with its user request")
    pending: set[str] = set()
    for message in group[1:]:
        if message.role == "tool":
            call_id = message.tool_call_id
            if call_id is None or call_id not in pending:
                raise AgentContextInvalid("Tool result does not match a pending call")
            pending.remove(call_id)
        elif message.role == "assistant":
            if pending:
                raise AgentContextInvalid("Assistant message interrupts pending tool results")
            pending.update(call.call_id for call in message.tool_calls)
        else:
            raise AgentContextInvalid("Unexpected role inside a conversation group")
    if pending:
        raise AgentContextInvalid("Tool calls are missing their results")


def _compaction_notice(omitted: int) -> AgentMessage:
    return AgentMessage(
        role="system",
        content=_canonical_json(
            {
                "history_compaction": {
                    "version": 1,
                    "omitted_groups": omitted,
                    "policy": "oldest_complete_user_turns",
                },
                "instruction": (
                    "Earlier conversation groups were omitted in full. "
                    "Do not invent missing facts. Current instructions and tool results "
                    "are preserved; read current facts with tools."
                ),
            }
        ),
    )


def fit_agent_context(
    *,
    messages: Sequence[AgentMessage],
    tools: Sequence[dict[str, Any]],
    max_bytes: int,
) -> AgentContext:
    """Drop oldest complete historical user groups until the request fits.

    All leading system messages and the final user request with its entire
    assistant/tool suffix are required. Tool definitions are required too.
    No individual content string, reference, constraint or call/result pair is
    truncated. The omission notice itself counts toward the request budget.

    Pass the original full transcript on every invocation, rather than feeding
    a prior projection back in. This keeps omission counts deterministic and
    lets later calls shed more history as current tool evidence grows.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise AgentContextInvalid("Agent context byte limit must be a positive integer")
    try:
        frozen_messages = [
            AgentMessage.model_validate(row.model_dump(mode="json")) for row in messages
        ]
    except ValidationError as exc:
        raise AgentContextInvalid("Agent context contains an invalid message") from exc
    if any(not isinstance(tool, dict) for tool in tools):
        raise AgentContextInvalid("Agent tool definitions must be JSON objects")
    # Validate/copy tools before fitting: a larger request is never reduced by
    # dropping a tool or silently changing its schema.
    frozen_tools = json.loads(_canonical_json(list(tools)))
    prefix_end = next(
        (index for index, message in enumerate(frozen_messages) if message.role != "system"),
        len(frozen_messages),
    )
    prefix = frozen_messages[:prefix_end]
    conversation = frozen_messages[prefix_end:]
    if not conversation or conversation[0].role != "user":
        raise AgentContextInvalid("Conversation is missing its first user request")
    starts = [index for index, message in enumerate(conversation) if message.role == "user"]
    groups = [
        conversation[start:end]
        for start, end in zip(starts, [*starts[1:], len(conversation)], strict=True)
    ]
    for group in groups:
        _validate_turn(group)
    history, current = groups[:-1], groups[-1]
    for omitted in range(len(history) + 1):
        projected = [
            *prefix,
            *([_compaction_notice(omitted)] if omitted else []),
            *(message for group in history[omitted:] for message in group),
            *current,
        ]
        request_json = _canonical_json(
            {
                "messages": [message.model_dump(mode="json") for message in projected],
                "tools": frozen_tools,
            }
        )
        encoded = request_json.encode("utf-8")
        if len(encoded) <= max_bytes:
            return AgentContext(
                request_json=request_json,
                request_bytes=len(encoded),
                omitted_history_groups=omitted,
                retained_history_groups=len(history) - omitted,
                context_hash=hashlib.sha256(encoded).hexdigest(),
            )
    raise AgentContextOverflow(
        required_bytes=len(encoded),
        max_bytes=max_bytes,
        omitted_history_groups=len(history),
    )
