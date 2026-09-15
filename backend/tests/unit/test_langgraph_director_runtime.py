"""D4 bounded LangGraph vertical slice over DramaForge domain ports."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from app.contracts.director_runtime import ResumeSignal, RuntimeInput, RuntimeScope, StopRequest
from app.contracts.production_commands import ExecutionReceipt
from app.contracts.production_facts import ExecutionFact
from app.director.runtime.langgraph_adapter import ENGINE_VERSION, LangGraphDirectorRuntime
from app.director.runtime.ports import RuntimeDecisionFact, RuntimeProposalFact
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from langgraph.checkpoint.memory import InMemorySaver


class FakeResumeClaims:
    def __init__(self) -> None:
        self._claimed: set[UUID] = set()
        self._lock = asyncio.Lock()

    async def claim(self, signal: ResumeSignal) -> bool:
        async with self._lock:
            if signal.signal_id in self._claimed:
                return False
            self._claimed.add(signal.signal_id)
            return True


class FakeRuntimeTools:
    def __init__(self, *, project_id: UUID) -> None:
        self.project_id = project_id
        self.proposal_id = uuid4()
        self.node_run_id = uuid4()
        self.artifact_id = uuid4()
        self.decisions: dict[UUID, str] = {}
        self.submit_attempts = 0
        self.production_creates = 0
        self.reject_submit = False
        self._receipts: dict[str, ExecutionReceipt] = {}

    async def propose(self, request: RuntimeInput) -> RuntimeProposalFact:
        assert request.input_reference
        return RuntimeProposalFact(proposal_id=self.proposal_id, proposal_version=3)

    async def decision(self, signal: ResumeSignal) -> RuntimeDecisionFact:
        return RuntimeDecisionFact(
            decision=self.decisions[signal.reference_id],  # type: ignore[arg-type]
            decision_version=signal.expected_revision,
        )

    async def submit_execution(
        self,
        *,
        request: RuntimeInput,
        proposal: RuntimeProposalFact,
        command_key: str,
    ) -> ExecutionReceipt:
        assert proposal.proposal_id == self.proposal_id
        assert request.scope.project_id == self.project_id
        if self.reject_submit:
            raise ValidationAppError(
                "Production authorization was revoked",
                details={"code": "PRODUCTION_COMMAND_NOT_AUTHORIZED"},
            )
        self.submit_attempts += 1
        if command_key not in self._receipts:
            self.production_creates += 1
            self._receipts[command_key] = ExecutionReceipt(
                node_run_id=self.node_run_id,
                graph_id=uuid4(),
                graph_version_id=uuid4(),
                status="queued",
                plan_fingerprint="a" * 64,
            )
        return self._receipts[command_key]

    async def execution_fact(self, signal: ResumeSignal) -> ExecutionFact:
        return ExecutionFact(
            id=self.node_run_id,
            project_id=self.project_id,
            shot_id=signal.reference_id,
            status="succeeded",
            stage="video",
            result_artifact_id=self.artifact_id,
        )


class DetachedRuntimeTools(FakeRuntimeTools):
    async def propose(self, request: RuntimeInput) -> RuntimeProposalFact:
        assert request.input_reference == request.turn_id
        return RuntimeProposalFact(proposal_id=None, proposal_version=3)

    async def decision(self, signal: ResumeSignal) -> RuntimeDecisionFact:
        return RuntimeDecisionFact(
            decision=self.decisions[signal.reference_id],  # type: ignore[arg-type]
            decision_version=signal.expected_revision,
            next_action="complete",
        )


class PreauthorizedRuntimeTools(FakeRuntimeTools):
    async def propose(self, request: RuntimeInput) -> RuntimeProposalFact:
        assert request.authorization_ref is not None
        return RuntimeProposalFact(
            proposal_id=self.proposal_id,
            proposal_version=1,
            command_key=f"approved:{request.authorization_ref}",
            persisted_decision="accept",
            next_action="execute",
        )


def _request(scope: RuntimeScope, turn_id: UUID, *, max_steps: int = 6) -> RuntimeInput:
    return RuntimeInput(
        scope=scope,
        turn_id=turn_id,
        runtime_execution_id=uuid4(),
        engine_version=ENGINE_VERSION,
        input_reference=uuid4(),
        max_steps=max_steps,
    )


def _signal(
    scope: RuntimeScope,
    turn_id: UUID,
    *,
    reason: str,
    reference_id: UUID,
    revision: int,
    signal_id: UUID | None = None,
) -> ResumeSignal:
    return ResumeSignal(
        scope=scope,
        turn_id=turn_id,
        signal_id=signal_id or uuid4(),
        reason=reason,  # type: ignore[arg-type]
        reference_id=reference_id,
        expected_revision=revision,
    )


@pytest.mark.asyncio
async def test_persisted_one_shot_decision_advances_without_a_second_user_signal() -> None:
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    authorization_id = uuid4()
    request = _request(scope, turn_id).model_copy(update={
        "authorization_ref": authorization_id,
    })
    tools = PreauthorizedRuntimeTools(project_id=scope.project_id)
    runtime = LangGraphDirectorRuntime(
        checkpointer=InMemorySaver(), tools=tools, resume_claims=FakeResumeClaims(),
    )

    waiting = await runtime.start(request)
    assert waiting.status == "awaiting_execution"
    assert waiting.wait_reason == "production_fact"
    assert waiting.dispatched_command_key == f"approved:{authorization_id}"
    assert tools.submit_attempts == 1
    assert tools.production_creates == 1


@pytest.mark.asyncio
async def test_interrupt_resume_receipt_replay_and_candidate_confirmation() -> None:
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    request = _request(scope, turn_id)
    tools = FakeRuntimeTools(project_id=scope.project_id)
    claims = FakeResumeClaims()
    saver = InMemorySaver()
    runtime = LangGraphDirectorRuntime(checkpointer=saver, tools=tools, resume_claims=claims)

    waiting_decision = await runtime.start(request)
    assert waiting_decision.status == "awaiting_user"
    assert waiting_decision.wait_reason == "proposal_decision"
    assert waiting_decision.proposal_id == tools.proposal_id
    assert waiting_decision.engine_version == ENGINE_VERSION
    assert waiting_decision.state_schema_version == "director-runtime-state-v1"
    assert tools.submit_attempts == 0

    decision_ref = uuid4()
    tools.decisions[decision_ref] = "accept"
    decision_signal = _signal(
        scope,
        turn_id,
        reason="user_decision",
        reference_id=decision_ref,
        revision=waiting_decision.revision,
    )
    waiting_execution = await runtime.resume(decision_signal)
    assert waiting_execution.status == "awaiting_execution"
    assert waiting_execution.node_run_ids == (tools.node_run_id,)
    assert tools.submit_attempts == 1
    assert tools.production_creates == 1
    with pytest.raises(ConflictError):
        await runtime.resume(decision_signal)
    assert tools.submit_attempts == 1
    assert tools.production_creates == 1

    restarted = LangGraphDirectorRuntime(checkpointer=saver, tools=tools, resume_claims=claims)
    fact_signal = _signal(
        scope,
        turn_id,
        reason="production_fact",
        reference_id=uuid4(),
        revision=waiting_execution.revision,
    )
    confirm = await restarted.resume(fact_signal)
    assert confirm.status == "awaiting_user"
    assert confirm.wait_reason == "confirm_candidate"
    assert tools.submit_attempts == 1

    confirmation_ref = uuid4()
    tools.decisions[confirmation_ref] = "accept"
    complete = await restarted.resume(_signal(
        scope,
        turn_id,
        reason="user_decision",
        reference_id=confirmation_ref,
        revision=confirm.revision,
    ))
    assert complete.status == "completed"
    assert complete.wait_reason == "candidate_confirmed"
    assert tools.production_creates == 1


@pytest.mark.asyncio
async def test_detached_shot_draft_decision_completes_without_production() -> None:
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    request = _request(scope, turn_id).model_copy(update={"input_reference": turn_id})
    tools = DetachedRuntimeTools(project_id=scope.project_id)
    runtime = LangGraphDirectorRuntime(
        checkpointer=InMemorySaver(), tools=tools, resume_claims=FakeResumeClaims(),
    )

    waiting = await runtime.start(request)
    assert waiting.status == "awaiting_user"
    assert waiting.proposal_id is None
    decision_ref = uuid4()
    tools.decisions[decision_ref] = "accept"
    completed = await runtime.resume(_signal(
        scope,
        turn_id,
        reason="user_decision",
        reference_id=decision_ref,
        revision=waiting.revision,
    ))
    assert completed.status == "completed"
    assert completed.wait_reason == "proposal_applied"
    assert tools.submit_attempts == 0
    assert tools.production_creates == 0


@pytest.mark.asyncio
async def test_scope_stop_and_step_limit_fail_closed() -> None:
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    tools = FakeRuntimeTools(project_id=scope.project_id)
    runtime = LangGraphDirectorRuntime(
        checkpointer=InMemorySaver(), tools=tools, resume_claims=FakeResumeClaims(),
    )
    waiting = await runtime.start(_request(scope, turn_id, max_steps=1))
    foreign_scope = RuntimeScope(
        workspace_id=scope.workspace_id,
        project_id=uuid4(),
        actor_id=scope.actor_id,
    )
    with pytest.raises(NotFoundError):
        await runtime.read(scope=foreign_scope, turn_id=turn_id)

    decision_ref = uuid4()
    tools.decisions[decision_ref] = "accept"
    with pytest.raises(ConflictError) as limited:
        await runtime.resume(_signal(
            scope,
            turn_id,
            reason="user_decision",
            reference_id=decision_ref,
            revision=waiting.revision,
        ))
    assert limited.value.details["code"] == "DIRECTOR_RUNTIME_STEP_LIMIT"
    assert tools.submit_attempts == 0

    stopped = await runtime.request_stop(StopRequest(
        scope=scope,
        turn_id=turn_id,
        request_id=uuid4(),
        expected_revision=waiting.revision,
    ))
    assert stopped.status == "cancelled"
    assert stopped.wait_reason == "user_stopped"


@pytest.mark.asyncio
async def test_concurrent_duplicate_resume_has_one_effective_advancer() -> None:
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    tools = FakeRuntimeTools(project_id=scope.project_id)
    runtime = LangGraphDirectorRuntime(
        checkpointer=InMemorySaver(), tools=tools, resume_claims=FakeResumeClaims(),
    )
    waiting = await runtime.start(_request(scope, turn_id))
    decision_ref = uuid4()
    tools.decisions[decision_ref] = "accept"
    signal = _signal(
        scope,
        turn_id,
        reason="user_decision",
        reference_id=decision_ref,
        revision=waiting.revision,
    )

    await asyncio.gather(runtime.resume(signal), runtime.resume(signal))
    settled = await runtime.read(scope=scope, turn_id=turn_id)
    assert settled.status == "awaiting_execution"
    assert tools.submit_attempts == 1
    assert tools.production_creates == 1


@pytest.mark.asyncio
async def test_domain_gate_rejects_stale_or_manual_action_before_command_receipt() -> None:
    scope = RuntimeScope(workspace_id=uuid4(), project_id=uuid4(), actor_id=uuid4())
    turn_id = uuid4()
    tools = FakeRuntimeTools(project_id=scope.project_id)
    tools.reject_submit = True
    runtime = LangGraphDirectorRuntime(
        checkpointer=InMemorySaver(), tools=tools, resume_claims=FakeResumeClaims(),
    )
    waiting = await runtime.start(_request(scope, turn_id))
    decision_ref = uuid4()
    tools.decisions[decision_ref] = "accept"

    with pytest.raises(ValidationAppError) as rejected:
        await runtime.resume(_signal(
            scope,
            turn_id,
            reason="user_decision",
            reference_id=decision_ref,
            revision=waiting.revision,
        ))
    assert rejected.value.details["code"] == "PRODUCTION_COMMAND_NOT_AUTHORIZED"
    assert tools.submit_attempts == 0
    assert tools.production_creates == 0
