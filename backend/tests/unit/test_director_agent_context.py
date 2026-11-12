"""Context budgets preserve current constraints and tool pairs without paid summaries."""

from __future__ import annotations

import hashlib
import json

import pytest
from app.contracts.agent import AgentMessage, AgentToolCall
from app.director.agent_context import (
    AgentContextInvalid,
    AgentContextOverflow,
    fit_agent_context,
)


def _message(role, content: str = "", **extra) -> AgentMessage:
    return AgentMessage(role=role, content=content, **extra)


def _tool_pair(call_id: str, result: str = "Read-only fact") -> list[AgentMessage]:
    return [
        _message(
            "assistant",
            tool_calls=[AgentToolCall(call_id=call_id, name="project_get", arguments={})],
        ),
        _message("tool", result, tool_call_id=call_id),
    ]


def _tools(description: str = "Read current project") -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "project_get",
                "description": description,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
    ]


def test_complete_request_budget_includes_tool_schemas_and_unicode_bytes() -> None:
    messages = [_message("system", "不得改写资料。"), _message("user", "请核对这座桥。")]
    tools = _tools()
    context = fit_agent_context(messages=messages, tools=tools, max_bytes=4096)
    payload = json.loads(context.request_json)
    assert payload["tools"] == tools
    assert payload["messages"] == [message.model_dump(mode="json") for message in messages]
    assert context.request_bytes == len(context.request_json.encode("utf-8"))
    assert context.request_bytes > len(context.request_json)
    assert context.context_hash == hashlib.sha256(context.request_json.encode("utf-8")).hexdigest()
    assert context.omitted_history_groups == 0
    with pytest.raises(AgentContextOverflow) as rejected:
        fit_agent_context(messages=messages, tools=_tools("schema" * 1000), max_bytes=4096)
    assert rejected.value.reason == "context_limit"
    assert rejected.value.required_bytes > 4096


def test_oldest_history_group_is_removed_whole_and_omission_notice_is_budgeted() -> None:
    messages = [
        _message("system", "Safety policy"),
        _message("system", '{"scope":"project-1","skill_hash":"frozen"}'),
        _message("user", "old-question" * 300),
        _message("assistant", "old-answer" * 300),
        _message("user", "recent question"),
        _message("assistant", "recent answer"),
        _message("user", "current request"),
    ]
    original = [row.model_dump(mode="json") for row in messages]
    context = fit_agent_context(messages=messages, tools=_tools(), max_bytes=1800)
    assert context.omitted_history_groups == 1
    assert context.retained_history_groups == 1
    assert context.request_bytes <= 1800
    assert [row.content for row in context.messages[:2]] == [row.content for row in messages[:2]]
    notice = json.loads(context.messages[2].content)
    assert notice["history_compaction"]["omitted_groups"] == 1
    assert [row.content for row in context.messages[3:]] == [
        "recent question",
        "recent answer",
        "current request",
    ]
    assert [row.model_dump(mode="json") for row in messages] == original


def test_historical_tools_are_removed_as_group_and_current_tools_remain_complete() -> None:
    current = [_message("user", "Keep the current constraints."), *_tool_pair("current-read")]
    messages = [
        _message("system", "Frozen scope and skills"),
        _message("user", "Old research"),
        *_tool_pair("old-read", "old evidence" * 500),
        _message("assistant", "Prior conclusion"),
        *current,
    ]
    context = fit_agent_context(messages=messages, tools=_tools(), max_bytes=2000)
    assert context.omitted_history_groups == 1
    assert [row.model_dump(mode="json") for row in context.messages[-3:]] == [
        row.model_dump(mode="json") for row in current
    ]
    assert "old-read" not in context.request_json
    assert "current-read" in context.request_json


@pytest.mark.parametrize("required_part", ["system", "current_user", "current_tool"])
def test_required_context_overflow_never_truncates_constraints_or_current_evidence(
    required_part,
) -> None:
    content = "关键约束" * 600
    messages = [
        _message("system", content if required_part == "system" else "Safety"),
        _message("user", "Old question"),
        _message("assistant", "Old answer"),
        _message("user", content if required_part == "current_user" else "Current request"),
    ]
    if required_part == "current_tool":
        messages.extend(_tool_pair("current", content))
    before = [message.model_dump(mode="json") for message in messages]
    with pytest.raises(AgentContextOverflow) as rejected:
        fit_agent_context(messages=messages, tools=_tools(), max_bytes=4096)
    assert rejected.value.omitted_history_groups == 1
    assert rejected.value.required_bytes > rejected.value.max_bytes
    assert [message.model_dump(mode="json") for message in messages] == before


def test_long_current_user_request_is_preserved_without_per_message_truncation() -> None:
    content = "cultural evidence " * 220 + " DO NOT LOSE THIS FINAL CONSTRAINT"
    context = fit_agent_context(
        messages=[_message("system", "Safety"), _message("user", content)],
        tools=[],
        max_bytes=8000,
    )
    assert context.messages[-1].content == content


def test_projection_is_stable_detached_and_can_shed_more_history_as_current_turn_grows() -> None:
    messages = [
        _message("system", "Safety"),
        _message("user", "old" * 600),
        _message("assistant", "old reply" * 600),
        _message("user", "recent" * 180),
        _message("assistant", "recent reply" * 80),
        _message("user", "current"),
    ]
    tools = _tools()
    first = fit_agent_context(messages=messages, tools=tools, max_bytes=4096)
    same = fit_agent_context(messages=messages, tools=tools, max_bytes=4096)
    assert first == same and first.omitted_history_groups == 1
    later = fit_agent_context(
        messages=[*messages, *_tool_pair("later", "fact" * 600)], tools=tools, max_bytes=4096
    )
    assert later.omitted_history_groups == 2
    assert json.loads(later.messages[1].content)["history_compaction"]["omitted_groups"] == 2
    assert first.context_hash != later.context_hash
    frozen = first.request_json
    messages[0].content = "changed caller data"
    tools[0]["function"]["description"] = "changed tool"
    first.messages[0].content = "changed accessor copy"
    first.tools[0]["function"]["description"] = "changed accessor copy"
    assert first.request_json == frozen
    assert first.messages[0].content == "Safety"
    assert first.tools[0]["function"]["description"] == "Read current project"


@pytest.mark.parametrize(
    "messages",
    [
        [_message("assistant", "orphaned history"), _message("user", "current")],
        [_message("user", "current"), _message("system", "late system instruction")],
        [_message("user", "current"), _tool_pair("pending")[0]],
        [_message("user", "current"), _message("tool", "orphaned result", tool_call_id="unknown")],
        [
            _message("user", "current"),
            _tool_pair("expected")[0],
            _message("tool", "wrong result", tool_call_id="different"),
        ],
        [_message("user", "old"), _tool_pair("pending")[0], _message("user", "current")],
    ],
)
def test_ambiguous_history_or_incomplete_pairs_are_rejected_instead_of_silently_repaired(
    messages,
) -> None:
    with pytest.raises(AgentContextInvalid) as rejected:
        fit_agent_context(messages=messages, tools=[], max_bytes=4096)
    assert rejected.value.reason == "context_invalid"


@pytest.mark.parametrize("max_bytes", [0, -1, True])
def test_invalid_budget_is_rejected(max_bytes) -> None:
    with pytest.raises(AgentContextInvalid):
        fit_agent_context(messages=[_message("user", "current")], tools=[], max_bytes=max_bytes)


def test_nonfinite_tool_contract_is_rejected() -> None:
    with pytest.raises(AgentContextInvalid):
        fit_agent_context(
            messages=[_message("user", "current")], tools=[{"limit": float("nan")}], max_bytes=4096
        )
