"""Exercise the real LangGraph loop with deterministic, non-network model/tool ports."""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.contracts.agent import AgentMessage, AgentModelResponse, AgentToolCall
from app.director.agent_harness import AgentHalt, AgentLimits, DirectorAgentHarness
from langgraph.checkpoint.memory import MemorySaver


def _call(name: str, call_id: str, **arguments: Any) -> AgentToolCall:
    return AgentToolCall(name=name, call_id=call_id, arguments=arguments)


def _paired(messages: list[dict[str, Any]]) -> None:
    pending: set[str] = set()
    for raw in messages:
        message = AgentMessage.model_validate(raw)
        if message.role == "tool":
            assert message.tool_call_id in pending, "tool result must match a pending call"
            pending.remove(message.tool_call_id)
        else:
            assert not pending, "all tool calls must receive results before another message"
            pending.update(call.call_id for call in message.tool_calls)
    assert not pending, "terminal transcripts must account for unexecuted tool calls"


class FakeModel:
    def __init__(self, responses: list[AgentModelResponse]) -> None:
        self.responses = responses
        self.inputs: list[list[AgentMessage]] = []

    async def __call__(self, messages: list[AgentMessage], step: int) -> AgentModelResponse:
        assert step == len(self.inputs) + 1
        _paired([message.model_dump(mode="json") for message in messages])
        self.inputs.append([message.model_copy(deep=True) for message in messages])
        assert step <= len(self.responses), "unexpected extra model submission"
        return self.responses[step - 1]


class FakeTools:
    def __init__(self, *, changing_versions: bool = False, payload: str = "") -> None:
        self.calls: list[AgentToolCall] = []
        self.changing_versions = changing_versions
        self.payload = payload

    async def __call__(self, call: AgentToolCall, step: int) -> dict[str, Any]:
        assert step == len(self.calls) + 1
        self.calls.append(call.model_copy(deep=True))
        return {
            "call_id": call.call_id,
            "ok": True,
            "data": {"text": self.payload},
            "observed_versions": {"project:p": step if self.changing_versions else 1},
        }


async def _allow() -> None:
    return None


def _inputs(content: str = "读取当前项目后回答。") -> list[AgentMessage]:
    return [
        AgentMessage(role="system", content="Tools are read-only; retain user gates."),
        AgentMessage(role="user", content=content),
    ]


@pytest.mark.parametrize(
    "sequence",
    [
        ["project_get", "scenes_list"],
        ["assets_list", "project_get", "asset_get"],
    ],
)
async def test_model_chooses_different_tool_sequences_and_checkpoint_retains_pairs(
    sequence,
) -> None:
    saver = MemorySaver()
    model = FakeModel(
        [
            *[
                AgentModelResponse(tool_calls=[_call(name, f"call-{index}")])
                for index, name in enumerate(sequence)
            ],
            AgentModelResponse(text="已读取，可以继续规划。", stop_reason="end_turn"),
        ]
    )
    tools = FakeTools()
    harness = DirectorAgentHarness(
        checkpointer=saver, limits=AgentLimits(), model=model, tool=tools, guard=_allow
    )
    state = await harness.run(messages=_inputs(), checkpoint_key="sequence")
    assert [call.name for call in tools.calls] == sequence
    assert state["stop_reason"] == "completed"
    assert state["model_calls"] == len(sequence) + 1
    assert state["tool_calls"] == len(sequence)
    assert state["answer"] == "已读取，可以继续规划。"
    _paired(state["messages"])
    saved = await saver.aget_tuple({"configurable": {"thread_id": "sequence"}})
    assert saved is not None
    assert saved.checkpoint["channel_values"]["messages"] == state["messages"]
    assert saved.checkpoint["channel_values"]["stop_reason"] == "completed"


async def test_context_projection_drops_history_but_checkpoint_keeps_full_audit() -> None:
    saver = MemorySaver()
    model = FakeModel([AgentModelResponse(text="已保留当前约束。", stop_reason="stop")])
    executor = FakeTools()
    system = [
        AgentMessage(role="system", content="Keep user gates; never invent missing source facts."),
        AgentMessage(role="system", content='{"scope":"project-1","skills":{"hash":"frozen"}}'),
    ]
    history = [
        AgentMessage(role="user", content="history-A-question; " * 400),
        AgentMessage(role="assistant", content="history-A-answer; " * 400),
        AgentMessage(role="user", content="history-B-question; " * 400),
        AgentMessage(role="assistant", content="history-B-answer; " * 400),
    ]
    current = AgentMessage(
        role="user",
        content="current cultural constraints; " * 100 + "最终约束：仅可读取原文。",
    )
    definitions = [
        {
            "type": "function",
            "function": {
                "name": "project_get",
                "description": "Read only the current project and preserve its version identity.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    original = [*system, *history, current]
    original_json = [message.model_dump(mode="json") for message in original]
    harness = DirectorAgentHarness(
        checkpointer=saver,
        limits=AgentLimits(context_bytes=8192),
        model=model,
        tool=executor,
        guard=_allow,
        tools=definitions,
    )
    state = await harness.run(messages=original, checkpoint_key="history-projection")
    assert state["stop_reason"] == "completed" and len(model.inputs) == 1
    assert executor.calls == []
    sent = model.inputs[0]
    assert [message.model_dump(mode="json") for message in sent[:2]] == original_json[:2]
    assert sent[-1].model_dump(mode="json") == current.model_dump(mode="json")
    assert json.loads(sent[2].content)["history_compaction"]["omitted_groups"] == 2
    assert all(
        "history-A" not in message.content and "history-B" not in message.content
        for message in sent
    )
    projection = harness.last_context
    assert projection is not None and projection.omitted_history_groups == 2
    assert projection.request_bytes <= 8192
    assert list(projection.tools) == definitions
    assert json.loads(projection.request_json)["tools"] == definitions
    assert state["messages"][: len(original_json)] == original_json
    saved = await saver.aget_tuple({"configurable": {"thread_id": "history-projection"}})
    assert saved is not None
    assert saved.checkpoint["channel_values"]["messages"][: len(original_json)] == original_json
    assert [message.model_dump(mode="json") for message in original] == original_json


async def test_model_observes_recoverable_tool_error_and_corrects_arguments() -> None:
    model = FakeModel(
        [
            AgentModelResponse(tool_calls=[_call("shots_list", "bad", scene_id="bad")]),
            AgentModelResponse(tool_calls=[_call("shots_list", "fixed", scene_id="scene-1")]),
            AgentModelResponse(text="该场镜头已读取。"),
        ]
    )
    executed: list[str] = []

    async def tool(call: AgentToolCall, step: int) -> dict[str, Any]:
        executed.append(call.call_id)
        if call.arguments["scene_id"] == "bad":
            return {
                "call_id": call.call_id,
                "ok": False,
                "error": {
                    "code": "ToolInputInvalid",
                    "recoverable": True,
                    "retry_class": "correct_input",
                },
            }
        return {"call_id": call.call_id, "ok": True, "data": {"items": []}}

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tool, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="correction")
    assert executed == ["bad", "fixed"]
    assert json.loads(model.inputs[1][-1].content)["error"]["code"] == "ToolInputInvalid"
    assert state["stop_reason"] == "completed"
    _paired(state["messages"])


@pytest.mark.parametrize("finish_reason", [None, "tool_calls"])
async def test_tool_only_model_message_executes_each_call_then_returns_to_model(
    finish_reason,
) -> None:
    model = FakeModel(
        [
            AgentModelResponse(
                tool_calls=[_call("project_get", "a"), _call("assets_list", "b")],
                stop_reason=finish_reason,
            ),
            AgentModelResponse(text="读取完成", stop_reason="stop"),
        ]
    )
    tools = FakeTools()
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="batch")
    assert state["model_calls"] == 2
    assert state["tool_calls"] == 2
    assert [message.role for message in model.inputs[1][-3:]] == ["assistant", "tool", "tool"]
    assert model.inputs[1][-3].content == ""
    _paired(state["messages"])


async def test_model_call_limit_blocks_next_submission_after_completed_tool_results() -> None:
    model = FakeModel(
        [
            AgentModelResponse(tool_calls=[_call("project_get", "a")]),
            AgentModelResponse(tool_calls=[_call("assets_list", "b")]),
        ]
    )
    tools = FakeTools()
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(),
        limits=AgentLimits(model_calls=2),
        model=model,
        tool=tools,
        guard=_allow,
    ).run(messages=_inputs(), checkpoint_key="model-limit")
    assert state["stop_reason"] == "model_call_limit"
    assert len(model.inputs) == state["model_calls"] == 2
    assert len(tools.calls) == state["tool_calls"] == 2
    _paired(state["messages"])


async def test_tool_limit_does_not_execute_extra_call_and_closes_pending_transcript() -> None:
    model = FakeModel(
        [
            AgentModelResponse(
                tool_calls=[_call("project_get", "executed"), _call("assets_list", "unexecuted")]
            )
        ]
    )
    tools = FakeTools()
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(),
        limits=AgentLimits(tool_calls=1),
        model=model,
        tool=tools,
        guard=_allow,
    ).run(messages=_inputs(), checkpoint_key="tool-limit")
    assert state["stop_reason"] == "tool_call_limit"
    assert len(model.inputs) == 1
    assert [call.call_id for call in tools.calls] == ["executed"]
    assert state["tool_calls"] == 1
    assert state["pending"] == []
    _paired(state["messages"])
    unexecuted = next(row for row in state["messages"] if row.get("tool_call_id") == "unexecuted")
    assert json.loads(unexecuted["content"])["ok"] is False


async def test_third_identical_call_with_same_observed_versions_stops_loop() -> None:
    model = FakeModel(
        [
            AgentModelResponse(tool_calls=[_call("shot_get", f"read-{step}", shot_id="shot-1")])
            for step in range(3)
        ]
    )
    tools = FakeTools()
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="repeated")
    assert state["stop_reason"] == "repeated_tool_call"
    assert len(model.inputs) == len(tools.calls) == 3
    _paired(state["messages"])


async def test_updated_observed_version_is_not_mistaken_for_no_progress() -> None:
    model = FakeModel(
        [
            *[
                AgentModelResponse(tool_calls=[_call("shot_get", f"read-{step}", shot_id="shot-1")])
                for step in range(4)
            ],
            AgentModelResponse(text="检测到版本变化。"),
        ]
    )
    tools = FakeTools(changing_versions=True)
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="versions")
    assert state["stop_reason"] == "completed"
    assert len(tools.calls) == 4
    _paired(state["messages"])


async def test_oversized_initial_context_is_rejected_without_model_or_tool_call() -> None:
    model = FakeModel([])
    tools = FakeTools()
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(),
        limits=AgentLimits(context_bytes=4096),
        model=model,
        tool=tools,
        guard=_allow,
    ).run(messages=_inputs("中" * 1400), checkpoint_key="large-input")
    assert state["stop_reason"] == "context_limit"
    assert model.inputs == []
    assert tools.calls == []
    assert state["messages"][-1]["content"] == "中" * 1400


async def test_tool_result_context_overflow_preserves_pairs_and_blocks_next_model_call() -> None:
    model = FakeModel([AgentModelResponse(tool_calls=[_call("project_get", "large-result")])])
    tools = FakeTools(payload="中" * 1400)
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(),
        limits=AgentLimits(context_bytes=4096),
        model=model,
        tool=tools,
        guard=_allow,
    ).run(messages=_inputs(), checkpoint_key="large-result")
    assert state["stop_reason"] == "context_limit"
    assert len(model.inputs) == len(tools.calls) == 1
    assert "中" * 1400 in state["messages"][-1]["content"]
    _paired(state["messages"])


@pytest.mark.parametrize("reason", ["user_stopped", "deadline_exceeded", "context_stale"])
async def test_guard_rejection_before_execution_has_zero_calls(reason) -> None:
    model = FakeModel([])
    tools = FakeTools()

    async def guard() -> None:
        raise AgentHalt(reason)

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=guard
    ).run(messages=_inputs(), checkpoint_key=f"guard-{reason}")
    assert state["stop_reason"] == reason
    assert state["model_calls"] == state["tool_calls"] == 0
    assert model.inputs == tools.calls == []


async def test_stop_after_model_returns_records_actual_call_without_executing_tools() -> None:
    model = FakeModel([AgentModelResponse(tool_calls=[_call("project_get", "not-run")])])
    tools = FakeTools()

    async def guard() -> None:
        if model.inputs:
            raise AgentHalt("user_stopped")

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=guard
    ).run(messages=_inputs(), checkpoint_key="stop-after-model")
    assert state["stop_reason"] == "user_stopped"
    assert len(model.inputs) == state["model_calls"] == 1
    assert state["tool_calls"] == 0
    assert tools.calls == []
    _paired(state["messages"])


async def test_stop_between_tools_prevents_next_execution_and_accounts_for_pending_call() -> None:
    model = FakeModel(
        [
            AgentModelResponse(
                tool_calls=[_call("project_get", "first"), _call("assets_list", "stopped")]
            )
        ]
    )
    tools = FakeTools()

    async def guard() -> None:
        if tools.calls:
            raise AgentHalt("user_stopped")

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=guard
    ).run(messages=_inputs(), checkpoint_key="stop-between-tools")
    assert state["stop_reason"] == "user_stopped"
    assert [call.call_id for call in tools.calls] == ["first"]
    assert len(model.inputs) == 1
    assert state["tool_calls"] == 1
    _paired(state["messages"])


async def test_pending_proposal_stops_batch_without_extra_tool_or_model_submission() -> None:
    model = FakeModel(
        [
            AgentModelResponse(
                tool_calls=[
                    _call("project_get", "read"),
                    _call("proposal_create", "propose"),
                    _call("assets_list", "after-proposal"),
                ]
            )
        ]
    )
    executed: list[str] = []

    async def tool(call: AgentToolCall, step: int) -> dict[str, Any]:
        executed.append(call.call_id)
        data = {"proposal_ids": ["proposal-1"]} if call.call_id == "propose" else {}
        return {"call_id": call.call_id, "ok": True, "data": data}

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tool, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="proposal-gate")
    assert executed == ["read", "propose"]
    assert len(model.inputs) == 1
    assert state["tool_calls"] == 2
    assert state["stop_reason"] == "completed"
    assert "Apply" in state["answer"]
    _paired(state["messages"])
    stopped = next(row for row in state["messages"] if row.get("tool_call_id") == "after-proposal")
    result = json.loads(stopped["content"])
    assert result["ok"] is False
    assert result["execution_status"] == "not_executed"
    assert result["error"]["reason"] == "proposal_pending"


@pytest.mark.parametrize(
    "result",
    [
        {"ok": False, "data": {"proposal_ids": ["uncommitted"]}},
        {"ok": True, "data": {"proposal_ids": []}},
    ],
)
async def test_failed_or_empty_proposal_result_does_not_claim_a_pending_proposal(result) -> None:
    model = FakeModel(
        [
            AgentModelResponse(tool_calls=[_call("proposal_create", "proposal")]),
            AgentModelResponse(text="未创建提案，请调整内容。"),
        ]
    )

    async def tool(call: AgentToolCall, step: int) -> dict[str, Any]:
        return {"call_id": call.call_id, **result}

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tool, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="no-proposal")
    assert len(model.inputs) == 2
    assert state["answer"] == "未创建提案，请调整内容。"
    _paired(state["messages"])


async def test_repeated_call_limit_closes_batch_without_extra_execution() -> None:
    model = FakeModel(
        [
            AgentModelResponse(
                tool_calls=[
                    _call("shot_get", f"same-{index}", shot_id="shot-1") for index in range(4)
                ]
            )
        ]
    )
    tools = FakeTools()
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="batch-repeat")
    assert state["stop_reason"] == "repeated_tool_call"
    assert len(tools.calls) == 3
    assert len(model.inputs) == 1
    _paired(state["messages"])


async def test_model_submission_halt_counts_attempt_and_never_retries() -> None:
    attempted: list[int] = []
    tools = FakeTools()

    async def model(messages: list[AgentMessage], step: int) -> AgentModelResponse:
        attempted.append(step)
        raise AgentHalt("unknown_submission")

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="unknown-submission")
    assert attempted == [1]
    assert state["model_calls"] == 1
    assert state["stop_reason"] == "unknown_submission"
    assert tools.calls == []


@pytest.mark.parametrize(
    "code,retry_class,stop_reason",
    [
        ("ContextStale", "refresh_context", "context_stale"),
        ("ToolPermissionDenied", "none", "permission_denied"),
        ("ToolPermissionDenied", "correct_input", "permission_denied"),
    ],
)
async def test_terminal_tool_result_is_preserved_before_stopping_remaining_calls(
    code, retry_class, stop_reason,
) -> None:
    model = FakeModel(
        [
            AgentModelResponse(
                tool_calls=[
                    _call("shot_get", "stale", shot_id="shot-1"),
                    _call("project_get", "not-run"),
                ]
            )
        ]
    )
    executed: list[str] = []

    async def tool(call: AgentToolCall, step: int) -> dict[str, Any]:
        executed.append(call.call_id)
        return {
            "call_id": call.call_id,
            "ok": False,
            "observed_versions": {"shot:shot-1": 2},
            "error": {
                "code": code,
                "retry_class": retry_class,
                "recoverable": False,
            },
        }

    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tool, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="stale-result")
    assert executed == ["stale"]
    assert len(model.inputs) == 1
    assert state["stop_reason"] == stop_reason
    _paired(state["messages"])
    stale = next(row for row in state["messages"] if row.get("tool_call_id") == "stale")
    assert json.loads(stale["content"])["observed_versions"] == {"shot:shot-1": 2}
    assert json.loads(stale["content"])["error"]["code"] == code
    skipped = next(row for row in state["messages"] if row.get("tool_call_id") == "not-run")
    assert json.loads(skipped["content"])["execution_status"] == "not_executed"


@pytest.mark.parametrize(
    "finish_reason,with_tools,expected",
    [
        ("length", False, "model_output_truncated"),
        ("length", True, "model_output_truncated"),
        ("content_filter", False, "model_output_blocked"),
        ("content_filter", True, "model_output_blocked"),
        ("refusal", False, "model_output_blocked"),
        ("refusal", True, "model_output_blocked"),
        ("unrecognized_reason", False, "model_stop_unsupported"),
        ("unrecognized_reason", True, "model_stop_unsupported"),
        ("tool_calls", False, "model_stop_unsupported"),
        ("stop", True, "model_stop_unsupported"),
        ("end_turn", True, "model_stop_unsupported"),
    ],
)
async def test_nonfinal_or_mismatched_model_stop_never_executes_tools_or_completes(
    finish_reason,
    with_tools,
    expected,
) -> None:
    model = FakeModel(
        [
            AgentModelResponse(
                text="This output must not be adopted as a complete answer.",
                tool_calls=[_call("project_get", "forbidden")] if with_tools else [],
                stop_reason=finish_reason,
            )
        ]
    )
    tools = FakeTools()
    state = await DirectorAgentHarness(
        checkpointer=MemorySaver(), limits=AgentLimits(), model=model, tool=tools, guard=_allow
    ).run(messages=_inputs(), checkpoint_key="model-stop")
    assert state["stop_reason"] == expected
    assert state["stop_reason"] != "completed"
    assert state["model_calls"] == len(model.inputs) == 1
    assert state["tool_calls"] == 0 and tools.calls == []
    assert state["answer"] == ""
    assert state["pending"] == []
    _paired(state["messages"])
