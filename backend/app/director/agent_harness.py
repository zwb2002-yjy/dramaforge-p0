"""Bounded LangGraph tool loop; persistence and authority belong to injected ports."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from importlib.metadata import version
from typing import Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.agent import AgentMessage, AgentModelResponse, AgentToolCall
from app.director.agent_context import (
    AgentContext,
    AgentContextInvalid,
    AgentContextOverflow,
    fit_agent_context,
)

STATE_VERSION = "director-agent-v1"
ENGINE_VERSION = f"langgraph:{version('langgraph')}:{STATE_VERSION}"


class AgentLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_calls: int = Field(default=6, ge=1, le=6)
    tool_calls: int = Field(default=12, ge=1, le=12)
    deadline_seconds: int = Field(default=120, ge=1, le=120)
    context_bytes: int = Field(default=64000, ge=4096, le=128000)


class AgentState(TypedDict):
    messages: list[dict[str, Any]]
    model_calls: int
    tool_calls: int
    pending: list[dict[str, Any]]
    repeated: list[str]
    stop_reason: str
    answer: str


class AgentHalt(Exception):
    """A safe terminal reason, never a signal to repeat a model submission."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class DirectorAgentHarness:
    def __init__(
        self,
        *,
        checkpointer: Any,
        limits: AgentLimits,
        model: Callable[[list[AgentMessage], int], Awaitable[AgentModelResponse]],
        tool: Callable[[AgentToolCall, int], Awaitable[dict[str, Any]]],
        guard: Callable[[], Awaitable[None]],
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        self._limits = limits
        self._model = model
        self._tool = tool
        self._guard = guard
        self._tools = tools or []
        self.last_context: AgentContext | None = None
        graph = StateGraph(AgentState)
        graph.add_node("model", self._model_step)
        graph.add_node("tools", self._tool_step)
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model",
            lambda state: "done" if state["stop_reason"] else "tools",
            {"done": END, "tools": "tools"},
        )
        graph.add_conditional_edges(
            "tools",
            lambda state: "done" if state["stop_reason"] else "model",
            {"done": END, "model": "model"},
        )
        self._graph = graph.compile(checkpointer=checkpointer)

    async def run(
        self,
        *,
        messages: list[AgentMessage],
        checkpoint_key: str,
    ) -> AgentState:
        config: RunnableConfig = {
            "configurable": {"thread_id": checkpoint_key},
            "recursion_limit": 16,
        }
        initial: AgentState = {
            "messages": [message.model_dump(mode="json") for message in messages],
            "model_calls": 0,
            "tool_calls": 0,
            "pending": [],
            "repeated": [],
            "stop_reason": "",
            "answer": "",
        }
        # Admission owns once-only execution. Re-entering HTTP reads the receipt;
        # it never uses a checkpoint to replay external side effects.
        return cast(AgentState, await self._graph.ainvoke(initial, config, durability="sync"))

    async def _model_step(self, state: AgentState) -> dict[str, Any]:
        count = state["model_calls"]
        try:
            await self._guard()
            if count >= self._limits.model_calls:
                raise AgentHalt("model_call_limit")
            projection = fit_agent_context(
                messages=[AgentMessage.model_validate(message) for message in state["messages"]],
                tools=self._tools,
                max_bytes=self._limits.context_bytes,
            )
            self.last_context = projection
            count += 1
            response = await self._model(
                list(projection.messages),
                count,
            )
            await self._guard()
            if response.stop_reason == "length":
                raise AgentHalt("model_output_truncated")
            if response.stop_reason in {"content_filter", "refusal"}:
                raise AgentHalt("model_output_blocked")
            allowed_reasons = (
                {None, "tool_calls"} if response.tool_calls else {None, "stop", "end_turn"}
            )
            if response.stop_reason not in allowed_reasons:
                # A partial/blocked/unknown response cannot authorize tool execution
                # or be presented as a completed answer, even when its JSON parses.
                raise AgentHalt("model_stop_unsupported")
            message = AgentMessage(
                role="assistant",
                content=response.text,
                tool_calls=response.tool_calls,
            )
            return {
                "messages": [*state["messages"], message.model_dump(mode="json")],
                "model_calls": count,
                "pending": [call.model_dump(mode="json") for call in response.tool_calls],
                "answer": response.text,
                "stop_reason": "" if response.tool_calls else "completed",
            }
        except AgentHalt as exc:
            # A late stop must not pretend the preceding model request never ran.
            return {"stop_reason": exc.reason, "model_calls": count}
        except (AgentContextInvalid, AgentContextOverflow) as exc:
            return {"stop_reason": exc.reason, "model_calls": count}

    async def _tool_step(self, state: AgentState) -> dict[str, Any]:
        messages = list(state["messages"])
        repeated = list(state["repeated"])
        count = state["tool_calls"]
        reason = ""
        answered: set[str] = set()
        attempted: set[str] = set()
        answer = state["answer"]
        try:
            for raw in state["pending"]:
                await self._guard()
                if count >= self._limits.tool_calls:
                    raise AgentHalt("tool_call_limit")
                call = AgentToolCall.model_validate(raw)
                count += 1
                attempted.add(call.call_id)
                result = await self._tool(call, count)
                fingerprint = json.dumps(
                    [call.name, call.arguments, result.get("observed_versions", {})],
                    sort_keys=True,
                    ensure_ascii=False,
                )
                repeated = [*repeated[-2:], fingerprint]
                messages.append(
                    AgentMessage(
                        role="tool",
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=call.call_id,
                    ).model_dump(mode="json")
                )
                answered.add(call.call_id)
                error = result.get("error")
                if isinstance(error, dict) and error.get("retry_class") == "refresh_context":
                    raise AgentHalt("context_stale")
                data = result.get("data")
                proposal_ids = data.get("proposal_ids") if isinstance(data, dict) else None
                if result.get("ok") is True and isinstance(proposal_ids, list) and proposal_ids:
                    # The trusted proposal port has committed actual pending rows.
                    # No further tool/model call may follow that user decision gate.
                    reason = "completed"
                    answer = "已生成待采纳提案，请审阅后明确 Apply；尚未修改正式内容。"
                    break
                if len(repeated) == 3 and len(set(repeated)) == 1:
                    raise AgentHalt("repeated_tool_call")
        except AgentHalt as exc:
            reason = exc.reason
        if reason:
            for raw in state["pending"]:
                call = AgentToolCall.model_validate(raw)
                if call.call_id in answered:
                    continue
                was_attempted = call.call_id in attempted
                result = {
                    "call_id": call.call_id,
                    "ok": False,
                    "execution_status": "not_completed" if was_attempted else "not_executed",
                    "error": {
                        "code": "AgentTurnStopped",
                        "reason": "proposal_pending" if reason == "completed" else reason,
                        "message": (
                            "Tool completion was not confirmed; do not replay the call."
                            if was_attempted
                            else "The turn stopped before this tool was executed."
                        ),
                        "recoverable": False,
                        "retry_class": "none",
                    },
                }
                messages.append(
                    AgentMessage(
                        role="tool",
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=call.call_id,
                    ).model_dump(mode="json")
                )
            if reason == "completed":
                messages.append(
                    AgentMessage(
                        role="assistant",
                        content=answer,
                    ).model_dump(mode="json")
                )
        return {
            "messages": messages,
            "tool_calls": count,
            "pending": [],
            "repeated": repeated,
            "stop_reason": reason,
            "answer": answer,
        }
