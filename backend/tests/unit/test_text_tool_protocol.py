"""Tool calls survive chat transport; malformed replies never become model text."""

import json

import httpx
import pytest
from app.config import Settings
from app.contracts.agent import AgentMessage, AgentModelResponse, AgentToolCall
from app.providers.bootstrap import default_text_manifest
from app.providers.capabilities import Capability
from app.providers.contracts.common import ExecutionContext, GenerationStatus
from app.providers.contracts.text import TextGenerateRequest, TextMessage
from app.providers.errors import InvalidOptionCombinationError
from app.providers.litellm_adapter import LiteLLMModelAdapter
from pydantic import ValidationError


def _adapter(handler):
    return LiteLLMModelAdapter(
        default_text_manifest(),
        settings=Settings(
            app_env="development",
            litellm_gateway_url="https://gateway.example",
            litellm_api_key="synthetic-key",
        ),
        transport=httpx.MockTransport(handler),
    )


def _call(*, call_id="read-1", arguments='{"shot_id":"shot-1"}'):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "read_shot", "arguments": arguments},
    }


async def test_tool_only_response_then_tool_result_round_trip():
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [_call()],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Shot is ready"}, "finish_reason": "stop"}],
            },
        )

    adapter = _adapter(handler)
    tool = {
        "type": "function",
        "function": {
            "name": "read_shot",
            "description": "Read the selected shot",
            "parameters": {"type": "object", "properties": {"shot_id": {"type": "string"}}},
        },
    }
    first = await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(
            messages=[TextMessage(role="user", content="Read shot-1")],
            tools=[tool],
            tool_choice="required",
            parallel_tool_calls=False,
        ),
        ExecutionContext(trace_id="turn"),
    )
    assert first.status == GenerationStatus.SUCCEEDED
    assert first.provider_metadata["text"] == ""
    assert first.provider_metadata["tool_calls"] == [
        {
            "call_id": "read-1",
            "name": "read_shot",
            "arguments": {"shot_id": "shot-1"},
        }
    ]
    assert first.provider_metadata["stop_reason"] == "tool_calls"
    assert first.provider_metadata["usage"]["total_tokens"] == 11
    assert requests[0]["tools"] == [tool]
    assert requests[0]["tool_choice"] == "required"
    assert requests[0]["parallel_tool_calls"] is False
    second = await adapter.create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(
            messages=[
                TextMessage(role="user", content="Read shot-1"),
                TextMessage.model_validate(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [_call()],
                    }
                ),
                TextMessage(
                    role="tool",
                    tool_call_id="read-1",
                    name="read_shot",
                    content='{"ok":true,"data":{"status":"ready"}}',
                ),
            ]
        ),
        ExecutionContext(trace_id="turn"),
    )
    assert second.status == GenerationStatus.SUCCEEDED
    assert second.provider_metadata["text"] == "Shot is ready"
    assert second.provider_metadata["tool_calls"] == []
    assert second.provider_metadata["stop_reason"] == "stop"
    assert requests[1]["messages"][1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [_call()],
    }
    assert requests[1]["messages"][2] == {
        "role": "tool",
        "tool_call_id": "read-1",
        "name": "read_shot",
        "content": '{"ok":true,"data":{"status":"ready"}}',
    }


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"content": "   "},
        {"content": {"unexpected": "sensitive-canary"}},
        {"content": None, "tool_calls": [_call(arguments="[]")]},
        {"content": None, "tool_calls": [_call(arguments="not-json sensitive-canary")]},
        {"content": None, "tool_calls": [_call(arguments='{"value":NaN}')]},
        {"content": None, "tool_calls": [_call(), _call()]},
        {"content": None, "tool_calls": [{"id": "x", "type": "shell"}]},
    ],
)
async def test_malformed_response_is_safe_failure_without_retry(message):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    result = await _adapter(handler).create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(messages=[TextMessage(role="user", content="read")]),
        ExecutionContext(trace_id="invalid"),
    )
    assert result.status == GenerationStatus.FAILED
    assert len(calls) == 1
    assert result.provider_metadata["stop_reason"] == "malformed_response"
    assert result.provider_metadata["usage"] == {"prompt_tokens": 4, "completion_tokens": 2}
    assert "sensitive-canary" not in json.dumps(result.provider_metadata)
    assert "text" not in result.provider_metadata


async def test_structured_response_keeps_schema_and_normalizes_usage():
    schema = {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": {"type": "object"}},
    }

    async def handler(request):
        assert json.loads(request.content)["response_format"] == schema
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": [{"type": "text", "text": '{"ok":true}'}]},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 1, "authorization": "secret"},
                    "completion_tokens_details": {"reasoning_tokens": 1},
                    "unknown": "secret",
                },
            },
        )

    result = await _adapter(handler).create(
        Capability.TEXT_GENERATE,
        TextGenerateRequest(
            messages=[TextMessage(role="user", content="answer")],
            response_format=schema,
        ),
        ExecutionContext(trace_id="structured"),
    )
    assert result.status == GenerationStatus.SUCCEEDED
    assert result.provider_metadata["text"] == '{"ok":true}'
    assert result.provider_metadata["usage"] == {
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 1},
        "completion_tokens_details": {"reasoning_tokens": 1},
    }


@pytest.mark.parametrize(
    "native",
    [
        {"messages": []},
        {"tools": []},
        {"tool_choice": "auto"},
        {"parallel_tool_calls": True},
    ],
)
async def test_native_options_cannot_replace_validated_tool_contract(native):
    async def handler(request):
        pytest.fail("invalid options must fail before a model call")

    with pytest.raises(InvalidOptionCombinationError):
        await _adapter(handler).create(
            Capability.TEXT_GENERATE,
            TextGenerateRequest(
                messages=[TextMessage(role="user", content="read")],
                native_options=native,
            ),
            ExecutionContext(trace_id="blocked"),
        )


@pytest.mark.parametrize(
    "message",
    [
        {"role": "tool", "content": "result"},
        {"role": "user", "content": "x", "tool_call_id": "call-1"},
        {"role": "user", "content": "x", "tool_calls": [_call()]},
        {"role": "assistant", "tool_calls": [_call(), _call()]},
    ],
)
def test_provider_messages_reject_invalid_role_contract(message):
    with pytest.raises(ValidationError):
        TextMessage.model_validate(message)


def test_neutral_contract_accepts_tool_only_and_rejects_ambiguous_calls():
    call = AgentToolCall(call_id="read-1", name="read_shot", arguments={"shot_id": "shot-1"})
    assert AgentModelResponse(tool_calls=[call]).text == ""
    assert AgentMessage(role="assistant", tool_calls=[call]).tool_calls == [call]
    assert AgentMessage(role="tool", tool_call_id=call.call_id, content="{}").content == "{}"
    for value in [
        {"role": "tool", "content": "{}"},
        {"role": "user", "content": "x", "tool_calls": [call]},
        {"role": "assistant", "tool_calls": [call, call]},
    ]:
        with pytest.raises(ValidationError):
            AgentMessage.model_validate(value)
    with pytest.raises(ValidationError):
        AgentModelResponse(text=" ")
    with pytest.raises(ValidationError):
        AgentToolCall.model_validate({"call_id": "x", "name": "read", "arguments": "{}"})


@pytest.mark.parametrize(
    "value",
    [
        {"call_id": "x" * 201, "name": "read", "arguments": {}},
        {"call_id": "x", "name": "x" * 161, "arguments": {}},
        {"call_id": "x", "name": "read", "arguments": {"value": "中" * 22000}},
        {"call_id": "x", "name": "read", "arguments": {"value": float("inf")}},
    ],
)
def test_tool_arguments_and_identity_are_bounded(value):
    with pytest.raises(ValidationError):
        AgentToolCall.model_validate(value)


def test_neutral_response_text_usage_and_tool_count_are_bounded():
    with pytest.raises(ValidationError):
        AgentModelResponse(text="x" * 32001)
    with pytest.raises(ValidationError):
        AgentModelResponse(text="ok", usage={"total_tokens": float("nan")})
    with pytest.raises(ValidationError):
        AgentModelResponse(
            tool_calls=[
                AgentToolCall(call_id=str(index), name="read", arguments={}) for index in range(13)
            ]
        )
    with pytest.raises(ValidationError):
        AgentModelResponse(
            tool_calls=[
                AgentToolCall(call_id=str(index), name="read", arguments={"v": "x" * 33000})
                for index in range(2)
            ]
        )
