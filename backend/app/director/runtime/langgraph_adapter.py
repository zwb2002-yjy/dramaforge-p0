"""Bounded LangGraph adapter over DramaForge-owned facts and commands."""

from __future__ import annotations

from importlib.metadata import version
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.contracts.director_runtime import (
    ResumeSignal,
    RuntimeInput,
    RuntimeScope,
    RuntimeView,
    StopRequest,
)
from app.contracts.production_facts import ExecutionFact
from app.director.runtime.ports import (
    DirectorRuntimeToolPort,
    RuntimeDecisionFact,
    RuntimeProposalFact,
    RuntimeResumeClaimPort,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

STATE_SCHEMA_VERSION = "director-runtime-state-v1"
ENGINE_VERSION = f"langgraph:{version('langgraph')}:{STATE_SCHEMA_VERSION}"


class DirectorGraphState(TypedDict, total=False):
    state_schema_version: str
    engine_version: str
    request: dict[str, object]
    workspace_id: str
    project_id: str
    actor_id: str
    turn_id: str
    runtime_execution_id: str
    revision: int
    status: str
    wait_reason: str | None
    step_count: int
    max_steps: int
    proposal: dict[str, object]
    decision: dict[str, object]
    receipt: dict[str, object]
    dispatched_command_key: str
    node_run_ids: list[str]
    production_fact: dict[str, object]
    stopped: bool


class LangGraphDirectorRuntime:
    """LangGraph owns position only; all domain truth comes from injected ports."""

    def __init__(self, *, checkpointer: Any, tools: DirectorRuntimeToolPort,
                 resume_claims: RuntimeResumeClaimPort) -> None:
        self._tools = tools
        self._resume_claims = resume_claims
        builder = StateGraph(DirectorGraphState)
        builder.add_node("propose", self._propose)
        builder.add_node("await_decision", self._await_decision)
        builder.add_node("submit_execution", self._submit_execution)
        builder.add_node("await_execution", self._await_execution)
        builder.add_node("confirm_candidate", self._confirm_candidate)
        builder.add_node("reject", self._reject)
        builder.add_node("complete_without_execution", self._complete_without_execution)
        builder.add_edge(START, "propose")
        builder.add_conditional_edges(
            "propose",
            self._proposal_route,
            {
                "await_decision": "await_decision",
                "execute": "submit_execution",
                "complete": "complete_without_execution",
                "reject": "reject",
            },
        )
        builder.add_conditional_edges(
            "await_decision",
            self._decision_route,
            {
                "execute": "submit_execution",
                "complete": "complete_without_execution",
                "reject": "reject",
            },
        )
        builder.add_edge("submit_execution", "await_execution")
        builder.add_conditional_edges(
            "await_execution",
            self._execution_route,
            {"confirm": "confirm_candidate", "finish": END},
        )
        builder.add_edge("confirm_candidate", END)
        builder.add_edge("complete_without_execution", END)
        builder.add_edge("reject", END)
        self._graph = builder.compile(checkpointer=checkpointer)

    async def start(self, request: RuntimeInput) -> RuntimeView:
        if request.engine_version != ENGINE_VERSION:
            raise ValidationAppError(
                "Director runtime engine version is not supported",
                details={"code": "DIRECTOR_ENGINE_VERSION_UNSUPPORTED"},
            )
        config = self._config(request.scope, request.turn_id)
        existing = await self._graph.aget_state(config)
        if existing.values:
            self._assert_scope(existing.values, request.scope, request.turn_id)
            if existing.values.get("runtime_execution_id") != str(request.runtime_execution_id):
                raise ConflictError(
                    "Director turn already belongs to another runtime execution",
                    details={"code": "DIRECTOR_ENGINE_BINDING_CONFLICT"},
                )
            return self._view(existing.values)
        initial: DirectorGraphState = {
            "state_schema_version": STATE_SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "request": request.model_dump(mode="json"),
            "workspace_id": str(request.scope.workspace_id),
            "project_id": str(request.scope.project_id),
            "actor_id": str(request.scope.actor_id),
            "turn_id": str(request.turn_id),
            "runtime_execution_id": str(request.runtime_execution_id),
            "revision": 1,
            "status": "queued",
            "wait_reason": "director_worker",
            "step_count": 0,
            "max_steps": request.max_steps,
            "node_run_ids": [],
            "stopped": False,
        }
        await self._graph.ainvoke(initial, config=config)
        return await self.read(scope=request.scope, turn_id=request.turn_id)

    async def resume(self, signal: ResumeSignal) -> RuntimeView:
        config = self._config(signal.scope, signal.turn_id)
        snapshot = await self._graph.aget_state(config)
        if not snapshot.values:
            raise NotFoundError("Director runtime checkpoint not found")
        self._assert_scope(snapshot.values, signal.scope, signal.turn_id)
        current = self._view(snapshot.values)
        if current.revision != signal.expected_revision:
            raise ConflictError(
                "Director runtime revision changed",
                details={
                    "code": "DIRECTOR_RUNTIME_REVISION_CONFLICT",
                    "revision": current.revision,
                },
            )
        if snapshot.values.get("stopped") or current.status in {
            "completed", "failed", "cancelled", "stale",
        }:
            return current
        if not await self._resume_claims.claim(signal):
            return await self.read(scope=signal.scope, turn_id=signal.turn_id)
        await self._graph.ainvoke(
            Command[Any](resume=signal.model_dump(mode="json")),
            config=config,
        )
        return await self.read(scope=signal.scope, turn_id=signal.turn_id)

    async def request_stop(self, request: StopRequest) -> RuntimeView:
        config = self._config(request.scope, request.turn_id)
        snapshot = await self._graph.aget_state(config)
        if not snapshot.values:
            raise NotFoundError("Director runtime checkpoint not found")
        self._assert_scope(snapshot.values, request.scope, request.turn_id)
        current = self._view(snapshot.values)
        if current.revision != request.expected_revision:
            raise ConflictError(
                "Director runtime revision changed",
                details={"code": "DIRECTOR_RUNTIME_REVISION_CONFLICT",
                         "revision": current.revision},
            )
        if current.status in {"completed", "failed", "cancelled", "stale"}:
            return current
        await self._graph.aupdate_state(
            config,
            {
                "stopped": True,
                "status": "cancelled",
                "wait_reason": "user_stopped",
                "revision": current.revision + 1,
            },
        )
        return await self.read(scope=request.scope, turn_id=request.turn_id)

    async def read(self, *, scope: RuntimeScope, turn_id: UUID) -> RuntimeView:
        snapshot = await self._graph.aget_state(self._config(scope, turn_id))
        if not snapshot.values:
            raise NotFoundError("Director runtime checkpoint not found")
        self._assert_scope(snapshot.values, scope, turn_id)
        return self._view(snapshot.values)

    async def _propose(self, state: DirectorGraphState) -> DirectorGraphState:
        self._require_step(state)
        request = RuntimeInput.model_validate(state["request"])
        proposal = await self._tools.propose(request)
        update: DirectorGraphState = {
            "proposal": proposal.model_dump(mode="json"),
            "status": "awaiting_user",
            "wait_reason": "proposal_decision",
            "step_count": state["step_count"] + 1,
            "revision": state["revision"] + 1,
        }
        if proposal.persisted_decision is not None:
            update.update({
                "decision": RuntimeDecisionFact(
                    decision=proposal.persisted_decision,
                    decision_version=proposal.proposal_version,
                    next_action=proposal.next_action,
                ).model_dump(mode="json"),
                "status": "thinking",
                "wait_reason": "decision_received",
            })
        return update

    @staticmethod
    def _proposal_route(
        state: DirectorGraphState,
    ) -> Literal["await_decision", "execute", "complete", "reject"]:
        raw = state.get("decision")
        if not raw:
            return "await_decision"
        decision = RuntimeDecisionFact.model_validate(raw)
        if decision.decision == "reject":
            return "reject"
        return decision.next_action

    async def _await_decision(self, state: DirectorGraphState) -> DirectorGraphState:
        raw = interrupt({
            "kind": "proposal_decision",
            "turn_id": state["turn_id"],
            "proposal_id": state["proposal"]["proposal_id"],
            "revision": state["revision"],
        })
        signal = ResumeSignal.model_validate(raw)
        if signal.reason != "user_decision":
            raise ValidationAppError(
                "Director runtime expected a user decision",
                details={"code": "DIRECTOR_RESUME_REASON_INVALID"},
            )
        decision = await self._tools.decision(signal)
        self._require_step(state)
        return {
            "decision": decision.model_dump(mode="json"),
            "status": "thinking",
            "wait_reason": "decision_received",
            "step_count": state["step_count"] + 1,
            "revision": state["revision"] + 1,
        }

    @staticmethod
    def _decision_route(
        state: DirectorGraphState,
    ) -> Literal["execute", "complete", "reject"]:
        decision = RuntimeDecisionFact.model_validate(state["decision"])
        return decision.next_action if decision.decision == "accept" else "reject"

    async def _submit_execution(self, state: DirectorGraphState) -> DirectorGraphState:
        self._require_step(state)
        request = RuntimeInput.model_validate(state["request"])
        proposal = RuntimeProposalFact.model_validate(state["proposal"])
        command_key = proposal.command_key or (
            f"director:{request.runtime_execution_id}:proposal:{proposal.proposal_version}"
        )
        receipt = await self._tools.submit_execution(
            request=request,
            proposal=proposal,
            command_key=command_key,
        )
        return {
            "receipt": receipt.model_dump(mode="json"),
            "dispatched_command_key": command_key,
            "node_run_ids": [str(receipt.node_run_id)],
            "status": "awaiting_execution",
            "wait_reason": "production_fact",
            "step_count": state["step_count"] + 1,
            "revision": state["revision"] + 1,
        }

    async def _await_execution(self, state: DirectorGraphState) -> DirectorGraphState:
        raw = interrupt({
            "kind": "production_fact",
            "turn_id": state["turn_id"],
            "node_run_ids": state["node_run_ids"],
            "revision": state["revision"],
        })
        signal = ResumeSignal.model_validate(raw)
        if signal.reason != "production_fact":
            raise ValidationAppError(
                "Director runtime expected a production fact",
                details={"code": "DIRECTOR_RESUME_REASON_INVALID"},
            )
        fact = await self._tools.execution_fact(signal)
        expected_run_id = UUID(state["node_run_ids"][0])
        if fact.id != expected_run_id or fact.project_id != UUID(state["project_id"]):
            raise ConflictError(
                "Production fact does not match the runtime receipt",
                details={"code": "DIRECTOR_PRODUCTION_FACT_MISMATCH"},
            )
        success = {
            "succeeded", "completed", "cached", "completed_after_cancel", "late_completed",
        }
        failed = {"failed", "cancelled"}
        if fact.status not in success | failed:
            raise ConflictError(
                "Production execution has not reached a successful terminal fact",
                details={"code": "DIRECTOR_PRODUCTION_NOT_COMPLETE", "status": fact.status},
            )
        self._require_step(state)
        return {
            "production_fact": fact.model_dump(mode="json"),
            "status": "awaiting_user" if fact.status in success else "failed",
            "wait_reason": (
                "confirm_candidate" if fact.status in success else "execution_failed"
            ),
            "step_count": state["step_count"] + 1,
            "revision": state["revision"] + 1,
        }

    @staticmethod
    def _execution_route(state: DirectorGraphState) -> Literal["confirm", "finish"]:
        fact = ExecutionFact.model_validate(state["production_fact"])
        return "finish" if fact.status in {"failed", "cancelled"} else "confirm"

    async def _confirm_candidate(self, state: DirectorGraphState) -> DirectorGraphState:
        raw = interrupt({
            "kind": "confirm_candidate",
            "turn_id": state["turn_id"],
            "artifact_id": state["production_fact"].get("result_artifact_id"),
            "revision": state["revision"],
        })
        signal = ResumeSignal.model_validate(raw)
        if signal.reason != "user_decision":
            raise ValidationAppError(
                "Director runtime expected candidate confirmation",
                details={"code": "DIRECTOR_RESUME_REASON_INVALID"},
            )
        decision = await self._tools.decision(signal)
        self._require_step(state)
        return {
            "decision": decision.model_dump(mode="json"),
            "status": "completed",
            "wait_reason": "candidate_confirmed" if decision.decision == "accept"
                           else "candidate_rejected",
            "step_count": state["step_count"] + 1,
            "revision": state["revision"] + 1,
        }

    async def _reject(self, state: DirectorGraphState) -> DirectorGraphState:
        return {
            "status": "completed",
            "wait_reason": "proposal_rejected",
        }

    async def _complete_without_execution(
        self, state: DirectorGraphState,
    ) -> DirectorGraphState:
        return {
            "status": "completed",
            "wait_reason": "proposal_applied",
        }

    @staticmethod
    def _require_step(state: DirectorGraphState) -> None:
        if state["step_count"] >= state["max_steps"]:
            raise ConflictError(
                "Director runtime reached its step limit",
                details={"code": "DIRECTOR_RUNTIME_STEP_LIMIT"},
            )

    @staticmethod
    def _config(scope: RuntimeScope, turn_id: UUID) -> RunnableConfig:
        return cast(RunnableConfig, {
            "configurable": {
                "thread_id": f"dramaforge:{scope.project_id}:{turn_id}",
            }
        })

    @staticmethod
    def _assert_scope(values: dict[str, Any], scope: RuntimeScope, turn_id: UUID) -> None:
        expected = (
            str(scope.workspace_id), str(scope.project_id), str(scope.actor_id), str(turn_id),
        )
        actual = (
            values.get("workspace_id"), values.get("project_id"),
            values.get("actor_id"), values.get("turn_id"),
        )
        if actual != expected:
            raise NotFoundError("Director runtime checkpoint not found")

    @staticmethod
    def _view(values: dict[str, Any]) -> RuntimeView:
        return RuntimeView(
            turn_id=UUID(str(values["turn_id"])),
            runtime_execution_id=UUID(str(values["runtime_execution_id"])),
            engine_version=str(values["engine_version"]),
            state_schema_version=str(values["state_schema_version"]),
            revision=int(values["revision"]),
            step_count=int(values["step_count"]),
            status=cast(Any, values["status"]),
            wait_reason=cast(str | None, values.get("wait_reason")),
            proposal_id=(
                UUID(str(values["proposal"]["proposal_id"]))
                if values.get("proposal") and values["proposal"].get("proposal_id")
                else None
            ),
            dispatched_command_key=cast(
                str | None, values.get("dispatched_command_key"),
            ),
            node_run_ids=tuple(UUID(item) for item in values.get("node_run_ids", [])),
        )


__all__ = [
    "ENGINE_VERSION",
    "STATE_SCHEMA_VERSION",
    "DirectorGraphState",
    "LangGraphDirectorRuntime",
]
