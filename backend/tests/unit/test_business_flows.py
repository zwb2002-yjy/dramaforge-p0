"""BusinessFlow definitions, dependencies, attempts and dispositions (T07)."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from app.director.business_flow_models import (
    DirectorBusinessFlowInstance,
    DirectorBusinessFlowStep,
    DirectorBusinessFlowStepAttempt,
)
from app.director.business_flows import (
    BusinessFlowDefinition,
    BusinessFlowDefinitionRegistry,
    BusinessFlowService,
    FlowActionError,
    FlowStepSpec,
)
from app.director.master_runs import MasterRunService
from app.shared.errors import ConflictError, ValidationAppError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from test_master_runs import _decision, _seed, _turn

PROBE = BusinessFlowDefinition(
    flow_key="probe_flow",
    definition_key="probe_flow",
    definition_version="1",
    state_schema_version="business-flow-state-v1",
    scope_type="project",
    steps=(
        FlowStepSpec(step_key="alpha", tool_name="project_get", action_kind="read"),
        FlowStepSpec(step_key="beta", tool_name="project_get", action_kind="read"),
        FlowStepSpec(
            step_key="gamma",
            tool_name="project_get",
            action_kind="read",
            dependencies=("alpha", "beta"),
        ),
    ),
    completion_rule_ids=("all_required_steps_succeeded", "no_unresolved_external"),
    resume_rule_id="retain_completed_steps",
    graph_entrypoint="probe_flow",
)
REGISTRY = BusinessFlowDefinitionRegistry((PROBE,))


class RecordingExecutor:
    """Fake controlled-tool executor; records concurrency and arguments."""

    def __init__(
        self,
        *,
        results: Mapping[str, dict[str, object]] | None = None,
        error: FlowActionError | None = None,
        barrier: int = 0,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.results = dict(results or {})
        self.error = error
        self.barrier = barrier
        self._both = asyncio.Event()
        self.max_in_flight = 0
        self._in_flight = 0

    async def execute(
        self,
        *,
        action_key: str,
        arguments: Mapping[str, object],
        call_id: str,
        scope_type: str,
        scope_entity_id: UUID,
        attempt_id: UUID,
        thread_id: UUID | None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "action_key": action_key,
                "arguments": dict(arguments),
                "call_id": call_id,
                "scope_type": scope_type,
                "scope_entity_id": scope_entity_id,
                "attempt_id": attempt_id,
                "thread_id": thread_id,
            }
        )
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            if self.barrier:
                if self._in_flight >= self.barrier:
                    self._both.set()
                await asyncio.wait_for(self._both.wait(), timeout=2)
            if self.error is not None:
                raise self.error
            return self.results.get(action_key, {"ok": True})
        finally:
            self._in_flight -= 1


def _plan(
    run,
    *,
    flows: list[dict[str, object]],
    current_plan=None,
    dispositions: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "goal": run.goal,
        "flows": flows,
        "dependencies": [],
        "completion": [{"rule_id": "all_required_steps_succeeded"}],
        "input_versions": {"project": 1},
        "limits": {"max_model_calls": 4, "max_steps": 6},
        "decision_basis": {
            "expected_run_revision": run.revision,
            "expected_control_epoch": run.control_epoch,
            "current_plan_id": str(run.current_plan_id) if run.current_plan_id else None,
            "current_plan_revision": current_plan.revision if current_plan else None,
        },
    }
    if dispositions is not None:
        data["flow_dispositions"] = dispositions
    return data


def _flow(
    *,
    flow_key: str = "probe_flow",
    definition_key: str = "probe_flow",
    input_data: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "flow_key": flow_key,
        "definition_key": definition_key,
        "definition_version": "1",
        "scope_type": "project",
        "scope_entity_id": None,
        "input": input_data or {"mark": "initial"},
    }


def _specs(project, flows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{**flow, "scope_entity_id": str(project.id)} for flow in flows]


async def _run_with_plan(
    session: AsyncSession,
    *,
    flows: list[dict[str, object]] | None = None,
    registry: BusinessFlowDefinitionRegistry = REGISTRY,
):
    project, user, thread = await _seed(session)
    specs = _specs(project, flows or [_flow()])
    service = MasterRunService(session, actor=user, project=project, flow_registry=registry)
    turn = await _turn(session, project, user, thread)
    run = await service.create_for_origin_turn(turn_id=turn.id, goal="整理古城资料")
    item = await _decision(session, project, user, thread)
    plan = await service.append_plan(
        run_id=run.id,
        decision_ref=item.id,
        plan_data=_plan(run, flows=specs),
        created_by_turn_id=turn.id,
    )
    await session.refresh(run)
    await service.apply_plan(
        run_id=run.id,
        plan_id=plan.id,
        expected_revision=run.revision,
        expected_control_epoch=run.control_epoch,
    )
    await session.refresh(run)
    return service, project, user, thread, run, plan


def test_registry_freezes_contracts_and_rejects_unknown_versions() -> None:
    registry = BusinessFlowDefinitionRegistry((PROBE,))
    same = BusinessFlowDefinition(
        flow_key=PROBE.flow_key,
        definition_key=PROBE.definition_key,
        definition_version=PROBE.definition_version,
        state_schema_version=PROBE.state_schema_version,
        scope_type=PROBE.scope_type,
        steps=PROBE.steps,
        completion_rule_ids=PROBE.completion_rule_ids,
        resume_rule_id=PROBE.resume_rule_id,
        graph_entrypoint=PROBE.graph_entrypoint,
    )
    assert same.contract_hash == PROBE.contract_hash
    registry.register(same)
    changed = BusinessFlowDefinition(
        flow_key=PROBE.flow_key,
        definition_key=PROBE.definition_key,
        definition_version=PROBE.definition_version,
        state_schema_version=PROBE.state_schema_version,
        scope_type=PROBE.scope_type,
        steps=(FlowStepSpec(step_key="only", tool_name="project_get", action_kind="read"),),
        completion_rule_ids=PROBE.completion_rule_ids,
        resume_rule_id=PROBE.resume_rule_id,
        graph_entrypoint=PROBE.graph_entrypoint,
    )
    with pytest.raises(ValueError):
        registry.register(changed)
    with pytest.raises(ValidationAppError) as unknown:
        registry.require("probe_flow", "9")
    assert unknown.value.details["code"] == "BUSINESS_FLOW_DEFINITION_UNKNOWN"
    with pytest.raises(ValueError):
        BusinessFlowDefinition(
            flow_key="cyclic",
            definition_key="cyclic",
            definition_version="1",
            state_schema_version="business-flow-state-v1",
            scope_type="project",
            steps=(
                FlowStepSpec(
                    step_key="a", tool_name="project_get", action_kind="read",
                    dependencies=("b",),
                ),
                FlowStepSpec(
                    step_key="b", tool_name="project_get", action_kind="read",
                    dependencies=("a",),
                ),
            ),
            completion_rule_ids=("all_required_steps_succeeded",),
            resume_rule_id="retain_completed_steps",
            graph_entrypoint="cyclic",
        )


async def test_plan_apply_creates_frozen_instances_steps_and_is_idempotent(
    session: AsyncSession,
) -> None:
    service, project, user, _thread, run, plan = await _run_with_plan(session)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    assert instance.supervisor_run_id == run.id and instance.plan_id == plan.id
    assert instance.plan_revision == plan.revision
    assert instance.definition_key == PROBE.definition_key
    assert instance.definition_version == "1"
    assert instance.contract_hash == PROBE.contract_hash
    assert instance.input_hash == hashlib.sha256(b'{"mark":"initial"}').hexdigest()
    assert instance.status == "pending"
    steps = list(
        await session.scalars(
            select(DirectorBusinessFlowStep).order_by(DirectorBusinessFlowStep.step_key)
        )
    )
    assert [step.step_key for step in steps] == ["alpha", "beta", "gamma"]
    assert steps[2].dependencies == ["alpha", "beta"]
    assert all(step.status == "pending" for step in steps)

    # A repeated create for the same (run, plan, flow_key) never duplicates rows.
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    again = await flows.create_from_plan(run=run, plan=plan)
    assert [item.id for item in again] == [instance.id]
    assert await session.scalar(select(func.count(DirectorBusinessFlowStep.id))) == 3


async def test_advance_runs_parallel_ready_steps_then_dependencies(
    session: AsyncSession,
) -> None:
    service, project, user, _thread, run, plan = await _run_with_plan(session)
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    executor = RecordingExecutor(barrier=2)

    advanced = await flows.advance(instance, executor=executor, max_parallel=2)

    assert executor.max_in_flight == 2  # alpha and beta really overlapped
    assert len(executor.calls) == 3
    assert advanced.status == "succeeded"
    assert advanced.terminal_reason == "all_required_steps_succeeded"
    assert advanced.finished_at is not None
    steps = {step.step_key: step for step in await flows.steps(instance.id)}
    assert {step.status for step in steps.values()} == {"succeeded"}
    attempts = list(await session.scalars(select(DirectorBusinessFlowStepAttempt)))
    assert len(attempts) == 3
    assert {attempt.command_key for attempt in attempts} == {
        f"flow:{step.id}:1" for step in steps.values()
    }
    assert all(attempt.receipt_ref == {"ok": True} for attempt in attempts)
    completion = await flows.completion(run=run, plan=plan)
    assert completion["satisfied"] is True
    progress = await flows.progress(run.id)
    assert progress == {
        "required_steps": 3,
        "completed_steps": 3,
        "waiting_user": 0,
        "waiting_execution": 0,
        "blocked_steps": 0,
        "unresolved_external_count": 0,
    }


async def test_proposal_step_waits_for_the_user_and_keeps_its_receipt(
    session: AsyncSession,
) -> None:
    service, project, user, _thread, run, plan = await _run_with_plan(session)
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    proposal_id = uuid4()
    executor = RecordingExecutor(
        results={"project_get": {"ok": True, "proposal_ids": [str(proposal_id)]}}
    )

    advanced = await flows.advance(instance, executor=executor)

    assert advanced.status == "waiting" and advanced.wait_reason == "user_decision"
    steps = {step.step_key: step for step in await flows.steps(instance.id)}
    assert steps["alpha"].status == "waiting_user"
    assert steps["gamma"].status == "pending"
    attempt = await session.scalar(select(DirectorBusinessFlowStepAttempt))
    assert attempt is not None and attempt.status == "succeeded"
    assert steps["alpha"].result_refs == [{"kind": "proposal", "id": str(proposal_id)}]
    assert (await flows.completion(run=run, plan=plan))["satisfied"] is False


async def test_unknown_submission_occupies_the_step_slot_and_is_not_retried(
    session: AsyncSession,
) -> None:
    _service, project, user, _thread, _run, _plan_row = await _run_with_plan(session)
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    executor = RecordingExecutor(
        error=FlowActionError("PROVIDER_SUBMISSION_UNKNOWN", unknown_submission=True)
    )

    advanced = await flows.advance(instance, executor=executor, max_parallel=1)

    assert advanced.status == "waiting" and advanced.wait_reason == "production_pending"
    attempts = list(await session.scalars(select(DirectorBusinessFlowStepAttempt)))
    assert len(attempts) == 2  # alpha and beta each own exactly one attempt
    assert {attempt.status for attempt in attempts} == {"unknown_submission"}
    assert all(attempt.unresolved_external is True for attempt in attempts)
    step = attempts[0]
    occupied = await session.get(DirectorBusinessFlowStep, step.step_id)
    assert occupied is not None and occupied.status == "waiting_execution"
    # The unresolved attempt still occupies the only active slot.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(
                DirectorBusinessFlowStepAttempt(
                    project_id=occupied.project_id,
                    step_id=occupied.id,
                    instance_id=occupied.instance_id,
                    supervisor_run_id=occupied.supervisor_run_id,
                    plan_id=occupied.plan_id,
                    plan_revision=occupied.plan_revision,
                    scope_type=occupied.scope_type,
                    scope_entity_id=occupied.scope_entity_id,
                    attempt_no=2,
                    control_epoch=0,
                    input_hash="a" * 64,
                    payload_hash="b" * 64,
                    input_snapshot={},
                    action_kind="read",
                    action_key="project_get",
                    command_key=f"manual:{uuid4()}",
                    status="pending",
                )
            )
            await session.flush()
    # A later advance never re-runs the occupied steps.
    second = RecordingExecutor()
    await flows.advance(instance, executor=second)
    assert second.calls == []


async def test_cancelled_pending_attempt_keeps_its_slot(session: AsyncSession) -> None:
    _service, project, user, _thread, _run, _plan_row = await _run_with_plan(session)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    step = await session.scalar(select(DirectorBusinessFlowStep))
    assert step is not None
    session.add(
        DirectorBusinessFlowStepAttempt(
            project_id=step.project_id,
            step_id=step.id,
            instance_id=step.instance_id,
            supervisor_run_id=step.supervisor_run_id,
            plan_id=step.plan_id,
            plan_revision=step.plan_revision,
            scope_type=step.scope_type,
            scope_entity_id=step.scope_entity_id,
            attempt_no=1,
            control_epoch=0,
            input_hash="a" * 64,
            payload_hash="b" * 64,
            input_snapshot={},
            action_kind="read",
            action_key="project_get",
            command_key=f"flow:{step.id}:1",
            status="cancelled",
            unresolved_external=True,
        )
    )
    await session.flush()
    # Cancelled locally but the remote effect is unresolved: still one slot.
    with pytest.raises(IntegrityError):
        session.add(
            DirectorBusinessFlowStepAttempt(
                project_id=step.project_id,
                step_id=step.id,
                instance_id=step.instance_id,
                supervisor_run_id=step.supervisor_run_id,
                plan_id=step.plan_id,
                plan_revision=step.plan_revision,
                scope_type=step.scope_type,
                scope_entity_id=step.scope_entity_id,
                attempt_no=2,
                control_epoch=0,
                input_hash="c" * 64,
                payload_hash="d" * 64,
                input_snapshot={},
                action_kind="read",
                action_key="project_get",
                command_key=f"flow:{step.id}:2",
                status="pending",
            )
        )
        await session.flush()
    await session.rollback()


async def test_new_plan_requires_dispositions_and_retains_only_identical_flows(
    session: AsyncSession,
) -> None:
    service, project, user, thread, run, first_plan = await _run_with_plan(session)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    await session.refresh(run)
    item = await _decision(session, project, user, thread)
    missing = await service.append_plan(
        run_id=run.id,
        decision_ref=item.id,
        plan_data=_plan(
            run,
            flows=_specs(project, [_flow()]),
            current_plan=first_plan,
        ),
    )
    with pytest.raises(ConflictError) as required:
        await service.apply_plan(
            run_id=run.id,
            plan_id=missing.id,
            expected_revision=run.revision,
            expected_control_epoch=run.control_epoch,
        )
    assert required.value.details["code"] == "BUSINESS_FLOW_DISPOSITION_REQUIRED"
    await session.rollback()
    session.info.pop("selected_workspace_id", None)

    service, project, user, thread, run, first_plan = await _run_with_plan(session)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    await session.refresh(run)
    item = await _decision(session, project, user, thread)
    retained = await service.append_plan(
        run_id=run.id,
        decision_ref=item.id,
        plan_data=_plan(
            run,
            flows=_specs(project, [_flow()]),
            current_plan=first_plan,
            dispositions=[{"instance_id": str(instance.id), "disposition": "retain"}],
        ),
    )
    await session.refresh(run)
    await service.apply_plan(
        run_id=run.id,
        plan_id=retained.id,
        expected_revision=run.revision,
        expected_control_epoch=run.control_epoch,
    )
    await session.refresh(instance)
    assert instance.status == "pending"
    # Retain is refused once the frozen input changed.
    await session.refresh(run)
    item = await _decision(session, project, user, thread)
    changed = await service.append_plan(
        run_id=run.id,
        decision_ref=item.id,
        plan_data=_plan(
            run,
            flows=_specs(project, [_flow(input_data={"mark": "changed"})]),
            current_plan=retained,
            dispositions=[{"instance_id": str(instance.id), "disposition": "retain"}],
        ),
    )
    await session.refresh(run)
    with pytest.raises(ConflictError) as ineligible:
        await service.apply_plan(
            run_id=run.id,
            plan_id=changed.id,
            expected_revision=run.revision,
            expected_control_epoch=run.control_epoch,
        )
    assert ineligible.value.details["code"] == "BUSINESS_FLOW_RETAIN_INELIGIBLE"
    await session.rollback()


async def test_cancel_run_keeps_successes_and_cancels_unfinished_steps(
    session: AsyncSession,
) -> None:
    _service, project, user, _thread, run, _plan_row = await _run_with_plan(session)
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None

    class ProposalOnceExecutor(RecordingExecutor):
        async def execute(self, **kwargs):
            await super().execute(**kwargs)
            return (
                {"ok": True, "proposal_ids": [str(uuid4())]}
                if len(self.calls) == 1
                else {"ok": True}
            )

    executor = ProposalOnceExecutor()
    await flows.advance(instance, executor=executor, max_parallel=1)
    steps = {step.step_key: step for step in await flows.steps(instance.id)}
    assert steps["alpha"].status == "waiting_user"
    assert steps["beta"].status == "succeeded"

    cancelled = await flows.cancel_run(run, reason="cancelled")

    assert cancelled == 1
    await session.refresh(instance)
    assert instance.status == "cancelled" and instance.terminal_reason == "cancelled"
    steps = {step.step_key: step for step in await flows.steps(instance.id)}
    assert steps["alpha"].status == "cancelled"
    assert steps["beta"].status == "succeeded"  # successes stay readable
    assert steps["gamma"].status == "cancelled"


async def test_definitions_must_reference_registered_controlled_tools(
    session: AsyncSession,
) -> None:
    bogus = BusinessFlowDefinition(
        flow_key="bogus_flow",
        definition_key="bogus_flow",
        definition_version="1",
        state_schema_version="business-flow-state-v1",
        scope_type="project",
        steps=(FlowStepSpec(step_key="only", tool_name="not_a_tool", action_kind="read"),),
        completion_rule_ids=("all_required_steps_succeeded",),
        resume_rule_id="retain_completed_steps",
        graph_entrypoint="bogus_flow",
    )
    registry = BusinessFlowDefinitionRegistry((bogus,))
    with pytest.raises(ValidationAppError) as refused:
        await _run_with_plan(
            session,
            flows=[_flow(flow_key="bogus_flow", definition_key="bogus_flow")],
            registry=registry,
        )
    assert refused.value.details["code"] == "BUSINESS_FLOW_TOOL_UNKNOWN"


async def test_stuck_running_attempt_is_failed_without_replay(
    session: AsyncSession,
) -> None:
    from datetime import UTC, datetime, timedelta

    _service, project, user, _thread, _run, _plan_row = await _run_with_plan(session)
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    step = await session.scalar(
        select(DirectorBusinessFlowStep).where(DirectorBusinessFlowStep.step_key == "alpha")
    )
    assert step is not None
    session.add(
        DirectorBusinessFlowStepAttempt(
            project_id=step.project_id,
            step_id=step.id,
            instance_id=step.instance_id,
            supervisor_run_id=step.supervisor_run_id,
            plan_id=step.plan_id,
            plan_revision=step.plan_revision,
            scope_type=step.scope_type,
            scope_entity_id=step.scope_entity_id,
            attempt_no=1,
            control_epoch=0,
            input_hash="a" * 64,
            payload_hash="b" * 64,
            input_snapshot={},
            action_kind="read",
            action_key="project_get",
            command_key=f"flow:{step.id}:1",
            status="running",
            updated_at=datetime.now(UTC) - timedelta(minutes=30),
        )
    )
    step.status = "running"
    await session.flush()

    executor = RecordingExecutor()
    advanced = await flows.advance(instance, executor=executor, max_parallel=1)

    assert executor.calls == []  # the lost attempt is never replayed
    attempt = await session.scalar(select(DirectorBusinessFlowStepAttempt))
    assert attempt is not None and attempt.status == "failed"
    assert attempt.error_code == "FLOW_ATTEMPT_STALE"
    await session.refresh(step)
    assert step.status == "failed"
    assert advanced.status == "failed"


async def test_worker_executor_maps_tool_receipts_and_failures(
    session: AsyncSession,
) -> None:
    from app.contracts.agent import AgentToolCall  # noqa: F401  (contract import only)
    from app.director.agent_tools import ToolResult
    from app.director.business_flow_worker import ToolFlowActionExecutor
    from app.shared.errors import ValidationAppError

    project, user, _thread = await _seed(session)
    executor = ToolFlowActionExecutor(
        lambda: session,
        actor_id=user.id,
        workspace_id=project.workspace_id,
        project_id=project.id,
    )

    async def ok(**kwargs):
        assert kwargs["name"] == "project_get"
        return ToolResult(call_id=kwargs["call_id"], ok=True, data={"id": str(project.id)})

    async def denied(**kwargs):
        raise ValidationAppError("ToolPermissionDenied")

    executor._executor.execute = ok  # type: ignore[method-assign]
    receipt = await executor.execute(
        action_key="project_get",
        arguments={},
        call_id="flow:1",
        scope_type="project",
        scope_entity_id=project.id,
        attempt_id=uuid4(),
        thread_id=None,
    )
    assert receipt["ok"] is True and receipt["data"]["id"] == str(project.id)
    executor._executor.execute = denied  # type: ignore[method-assign]
    with pytest.raises(FlowActionError) as refused:
        await executor.execute(
            action_key="project_get",
            arguments={},
            call_id="flow:2",
            scope_type="project",
            scope_entity_id=project.id,
            attempt_id=uuid4(),
            thread_id=None,
        )
    assert refused.value.code


async def test_worker_scan_finds_only_instances_with_actionable_steps(
    session: AsyncSession,
) -> None:
    from app.shared.db import list_pending_business_flow_rls_scopes

    _service, project, user, _thread, run, _plan_row = await _run_with_plan(session)
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    async with session.begin_nested():
        found = await list_pending_business_flow_rls_scopes(session, limit=10)
    assert [item_id for item_id, _scope in found] == [instance.id]
    await flows.cancel_run(run, reason="cancelled")
    async with session.begin_nested():
        assert await list_pending_business_flow_rls_scopes(session, limit=10) == []


async def test_completion_requires_every_registered_rule(session: AsyncSession) -> None:
    _service, project, user, _thread, run, plan = await _run_with_plan(session)
    flows = BusinessFlowService(session, actor=user, project=project, registry=REGISTRY)
    instance = await session.scalar(select(DirectorBusinessFlowInstance))
    assert instance is not None
    empty = await flows.completion(run=run, plan=plan)
    assert empty["satisfied"] is False
    await flows.advance(instance, executor=RecordingExecutor(), max_parallel=2)
    satisfied = await flows.completion(run=run, plan=plan)
    assert satisfied["satisfied"] is True
    checks = {check["rule_id"]: check for check in satisfied["checks"]}
    assert checks["all_required_steps_succeeded"]["completed_steps"] == 3
    assert checks["no_unresolved_external"]["unresolved_external_count"] == 0
    assert checks["business_flow_completed_v1"]["completed_flows"] == 1


def test_default_registry_carries_the_domain_flows() -> None:
    from app.director.business_flows import (
        DEFAULT_DEFINITIONS,
        PROJECT_ASSET_AUDIT_V1,
        SCENE_PROMPT_REVIEW_V1,
        SHOT_MODEL_CONTRACT_REVIEW_V1,
        SHOT_PROMPT_REVIEW_V1,
    )

    assert set(DEFAULT_DEFINITIONS.keys()) == {
        SHOT_PROMPT_REVIEW_V1.flow_key,
        SCENE_PROMPT_REVIEW_V1.flow_key,
        SHOT_MODEL_CONTRACT_REVIEW_V1.flow_key,
        PROJECT_ASSET_AUDIT_V1.flow_key,
    }
    for definition in (
        SHOT_PROMPT_REVIEW_V1,
        SCENE_PROMPT_REVIEW_V1,
        SHOT_MODEL_CONTRACT_REVIEW_V1,
        PROJECT_ASSET_AUDIT_V1,
    ):
        registered = DEFAULT_DEFINITIONS.require(
            definition.definition_key, definition.definition_version
        )
        assert registered.contract_hash == definition.contract_hash
        assert registered.steps
        assert registered.completion_rule_ids
    assert SCENE_PROMPT_REVIEW_V1.scope_type == "scene"
    assert SHOT_MODEL_CONTRACT_REVIEW_V1.scope_type == "shot"
    assert PROJECT_ASSET_AUDIT_V1.scope_type == "project"


def test_domain_flow_tools_exist_in_the_worker_registry() -> None:
    from app.director.agent_tools import ToolRegistry
    from app.director.business_flows import DEFAULT_DEFINITIONS

    names = {spec.name for spec in ToolRegistry(include_model_tools=True).specs()}
    for definition in DEFAULT_DEFINITIONS.definitions():
        for step in definition.steps:
            assert step.tool_name in names, (definition.flow_key, step.tool_name)
