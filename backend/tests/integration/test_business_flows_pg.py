"""BusinessFlow PostgreSQL proof: RLS, append-only, slot uniqueness, dispositions."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.director.assistant_models import DirectorThread
from app.director.business_flow_models import (
    DirectorBusinessFlowInstance,
    DirectorBusinessFlowStep,
    DirectorBusinessFlowStepAttempt,
)
from app.director.business_flows import (
    BusinessFlowDefinition,
    BusinessFlowDefinitionRegistry,
    BusinessFlowService,
    FlowStepSpec,
)
from app.director.master_runs import MasterRunService
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from pg_support import alembic_head
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

BACKEND = Path(__file__).resolve().parents[2]

FLOW = BusinessFlowDefinition(
    flow_key="pg_probe",
    definition_key="pg_probe",
    definition_version="1",
    state_schema_version="business-flow-state-v1",
    scope_type="project",
    steps=(
        FlowStepSpec(step_key="read", tool_name="project_get", action_kind="read"),
        FlowStepSpec(
            step_key="propose",
            tool_name="shot_prompt_propose",
            action_kind="proposal",
            dependencies=("read",),
        ),
    ),
    completion_rule_ids=("all_required_steps_succeeded", "no_unresolved_external"),
    resume_rule_id="retain_completed_steps",
    graph_entrypoint="pg_probe",
)
REGISTRY = BusinessFlowDefinitionRegistry((FLOW,))


class StaticExecutor:
    async def execute(self, **kwargs):
        return {"ok": True, "proposal_ids": [str(uuid4())]}


def migration(name: str, direction: str, target: str | None = None):
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, *([target] if target else [])],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": _async_url(name)},
        capture_output=True,
        text=True,
        check=False,
    )


@asynccontextmanager
async def flow_database():
    name = f"dramaforge_flows_{uuid4().hex[:10]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        _alembic(name)
        yield name, engine, factory
    finally:
        await engine.dispose()
        await _drop_database(name)


async def _seed(session):
    owner = User(email=f"{uuid4()}@example.com", display_name="Owner", password_hash="x")
    other = User(email=f"{uuid4()}@example.com", display_name="Other", password_hash="x")
    session.add_all([owner, other])
    await session.flush()
    workspace = Workspace(name="机构", owner_user_id=owner.id)
    foreign_workspace = Workspace(name="其它", owner_user_id=other.id)
    session.add_all([workspace, foreign_workspace])
    await session.flush()
    project = Project(
        workspace_id=workspace.id, name="甲", aspect_ratio="16:9", budget_limit=0,
        work_type="serial_comic",
    )
    other_project = Project(
        workspace_id=foreign_workspace.id, name="乙", aspect_ratio="16:9", budget_limit=0,
        work_type="serial_comic",
    )
    session.add_all([project, other_project])
    await session.flush()
    thread = DirectorThread(
        project_id=project.id, scope_type="project", scope_entity_id=project.id,
        title="机构创作", created_by=owner.id,
    )
    session.add(thread)
    await session.flush()
    turn = DirectorTurn(
        workspace_id=workspace.id, project_id=project.id, actor_id=owner.id,
        thread_id=thread.id, turn_kind="agent", scope_type="project",
        scope_entity_id=project.id, request_key=f"turn-{uuid4().hex}",
        context_hash="a" * 64, status="thinking",
    )
    session.add(turn)
    await session.flush()
    proposal = DirectorProposal(
        project_id=project.id, thread_id=thread.id, scope_type="project",
        scope_entity_id=project.id, created_by=owner.id,
    )
    session.add(proposal)
    await session.flush()
    item = DirectorProposalItem(
        proposal_id=proposal.id, project_id=project.id,
        command="director.master_run_plan_apply", payload={}, status="pending",
    )
    session.add(item)
    await session.flush()
    return owner, workspace, project, other_project, thread, turn, item


def _flow_spec(project_id: UUID, *, mark: str = "keep") -> dict[str, object]:
    return {
        "flow_key": "pg_probe",
        "definition_key": "pg_probe",
        "definition_version": "1",
        "scope_type": "project",
        "scope_entity_id": str(project_id),
        "input": {"mark": mark},
    }


def _plan(run, *, flows, current_plan=None, dispositions=None):
    data = {
        "goal": run.goal,
        "flows": flows,
        "dependencies": [],
        "completion": [{"rule_id": "all_required_steps_succeeded"}],
        "input_versions": {},
        "limits": {"max_steps": 3},
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


async def _apply_first_plan(factory, *, mark: str = "keep"):
    async with factory() as session:
        owner, workspace, project, other_project, thread, turn, item = await _seed(session)
        session.info["selected_workspace_id"] = workspace.id
        service = MasterRunService(
            session, actor=owner, project=project, flow_registry=REGISTRY,
        )
        run = await service.create_for_origin_turn(turn_id=turn.id, goal="整理古城灯会资料")
        plan = await service.append_plan(
            run_id=run.id,
            decision_ref=item.id,
            plan_data=_plan(run, flows=[_flow_spec(project.id, mark=mark)]),
        )
        await session.refresh(run)
        await service.apply_plan(
            run_id=run.id,
            plan_id=plan.id,
            expected_revision=run.revision,
            expected_control_epoch=run.control_epoch,
        )
        await session.commit()
        instance_id = await session.scalar(select(DirectorBusinessFlowInstance.id))
        return {
            "owner_id": owner.id,
            "workspace_id": workspace.id,
            "project_id": project.id,
            "other_project_id": other_project.id,
            "thread_id": thread.id,
            "run_id": run.id,
            "plan_id": plan.id,
            "instance_id": instance_id,
        }


async def test_flow_tables_are_project_scoped_append_only_and_cross_project_safe():
    async with flow_database() as (_name, engine, factory):
        ids = await _apply_first_plan(factory)
        async with factory() as session:
            instance = await session.scalar(select(DirectorBusinessFlowInstance))
            assert instance is not None
            instance_id = instance.id
            step = await session.scalar(select(DirectorBusinessFlowStep))
            assert step is not None
            step_id = step.id

        # A foreign project's scope cannot see these rows under the app role.
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["owner_id"],
                workspace_id=ids["workspace_id"],
                project_id=ids["other_project_id"],
            )
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            assert await session.scalar(select(func.count(DirectorBusinessFlowInstance.id))) == 0
            assert await session.scalar(select(func.count(DirectorBusinessFlowStep.id))) == 0
            await session.rollback()

        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["owner_id"],
                workspace_id=ids["workspace_id"],
                project_id=ids["project_id"],
            )
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            assert await session.scalar(select(func.count(DirectorBusinessFlowInstance.id))) == 1
            # Runtime role may update progress but never delete evidence.
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        text("DELETE FROM director_business_flow_instances WHERE id=:id"),
                        {"id": instance_id},
                    )
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        text("TRUNCATE director_business_flow_step_attempts")
                    )
            async with session.begin_nested():
                await session.execute(
                    text(
                        "UPDATE director_business_flow_instances SET status='waiting', "
                        "wait_reason='flow_progress_pending', revision=revision+1 WHERE id=:id"
                    ),
                    {"id": instance_id},
                )
            await session.rollback()

        # Composite scope keys reject forged cross-project links. They are
        # deferred, so the refusal surfaces at commit.
        async with factory() as session:
            session.add(
                DirectorBusinessFlowStep(
                    project_id=ids["other_project_id"],
                    instance_id=instance_id,
                    supervisor_run_id=ids["run_id"],
                    plan_id=ids["plan_id"],
                    plan_revision=1,
                    step_key="forged",
                    scope_type="project",
                    scope_entity_id=ids["other_project_id"],
                    input_refs={},
                    completion_spec={},
                    dependencies=[],
                    result_refs=[],
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO director_business_flow_step_attempts "
                    "(id, project_id, step_id, instance_id, supervisor_run_id, plan_id, "
                    "plan_revision, scope_type, scope_entity_id, attempt_no, control_epoch, "
                    "input_hash, payload_hash, input_snapshot, action_kind, action_key, "
                    "command_key, result_refs, unresolved_external, revision, status) "
                    "VALUES (:id, :project, :step, :instance, :run, :plan, 1, 'project', "
                    ":project, 1, 0, :hash, :hash, '{}'::jsonb, 'read', 'project_get', "
                    ":key, '[]'::jsonb, false, 1, 'pending')"
                ),
                {
                    "id": uuid4(),
                    "project": ids["project_id"],
                    "step": step_id,
                    "instance": uuid4(),  # forged instance identity
                    "run": ids["run_id"],
                    "plan": ids["plan_id"],
                    "hash": "a" * 64,
                    "key": f"forged:{uuid4()}",
                },
            )
            with pytest.raises(IntegrityError):
                await session.commit()


async def test_only_one_active_attempt_per_step_even_after_local_cancel():
    async with flow_database() as (_name, _engine, factory):
        ids = await _apply_first_plan(factory)
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["owner_id"],
                workspace_id=ids["workspace_id"],
                project_id=ids["project_id"],
            )
            step = await session.scalar(select(DirectorBusinessFlowStep))
            assert step is not None

            def attempt(*, number: int, status: str, unresolved: bool):
                return DirectorBusinessFlowStepAttempt(
                    project_id=step.project_id,
                    step_id=step.id,
                    instance_id=step.instance_id,
                    supervisor_run_id=step.supervisor_run_id,
                    plan_id=step.plan_id,
                    plan_revision=step.plan_revision,
                    scope_type=step.scope_type,
                    scope_entity_id=step.scope_entity_id,
                    attempt_no=number,
                    control_epoch=0,
                    input_hash="a" * 64,
                    payload_hash="b" * 64,
                    input_snapshot={},
                    action_kind="read",
                    action_key="project_get",
                    command_key=f"flow:{step.id}:{number}",
                    status=status,
                    unresolved_external=unresolved,
                )

            session.add(attempt(number=1, status="running", unresolved=False))
            await session.flush()
            # A second active attempt is refused by the partial unique index.
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(attempt(number=2, status="pending", unresolved=False))
                    await session.flush()
            # Cancelled locally but unresolved externally still occupies the slot.
            async with session.begin_nested():
                await session.execute(
                    text(
                        "UPDATE director_business_flow_step_attempts SET status='cancelled', "
                        "unresolved_external=true WHERE step_id=:step"
                    ),
                    {"step": step.id},
                )
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(attempt(number=3, status="pending", unresolved=False))
                    await session.flush()


async def test_plan_change_requires_dispositions_and_unknown_keeps_its_slot():
    async with flow_database() as (_name, _engine, factory):
        ids = await _apply_first_plan(factory)
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["owner_id"],
                workspace_id=ids["workspace_id"],
                project_id=ids["project_id"],
            )
            owner = await session.get(User, ids["owner_id"])
            project = await session.get(Project, ids["project_id"])
            assert owner is not None and project is not None
            service = MasterRunService(
                session, actor=owner, project=project, flow_registry=REGISTRY,
            )
            run = await service.get(ids["run_id"])
            instance = await session.scalar(select(DirectorBusinessFlowInstance))
            assert instance is not None
            thread_id = ids["thread_id"]
            proposal = DirectorProposal(
                project_id=project.id, thread_id=thread_id, scope_type="project",
                scope_entity_id=project.id, created_by=owner.id,
            )
            session.add(proposal)
            await session.flush()
            item = DirectorProposalItem(
                proposal_id=proposal.id, project_id=project.id,
                command="director.master_run_plan_apply", payload={}, status="pending",
            )
            session.add(item)
            await session.flush()
            first_plan = await service.get_plan(run.id, ids["plan_id"])
            missing = await service.append_plan(
                run_id=run.id,
                decision_ref=item.id,
                plan_data=_plan(
                    run,
                    flows=[_flow_spec(project.id)],
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

        # Retain keeps the original instance; a changed input cannot retain.
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["owner_id"],
                workspace_id=ids["workspace_id"],
                project_id=ids["project_id"],
            )
            owner = await session.get(User, ids["owner_id"])
            project = await session.get(Project, ids["project_id"])
            assert owner is not None and project is not None
            service = MasterRunService(
                session, actor=owner, project=project, flow_registry=REGISTRY,
            )
            run = await service.get(ids["run_id"])
            instance = await session.scalar(select(DirectorBusinessFlowInstance))
            assert instance is not None
            proposal = DirectorProposal(
                project_id=project.id, thread_id=ids["thread_id"], scope_type="project",
                scope_entity_id=project.id, created_by=owner.id,
            )
            session.add(proposal)
            await session.flush()
            item = DirectorProposalItem(
                proposal_id=proposal.id, project_id=project.id,
                command="director.master_run_plan_apply", payload={}, status="pending",
            )
            session.add(item)
            await session.flush()
            first_plan = await service.get_plan(run.id, ids["plan_id"])
            retained = await service.append_plan(
                run_id=run.id,
                decision_ref=item.id,
                plan_data=_plan(
                    run,
                    flows=[_flow_spec(project.id)],
                    current_plan=first_plan,
                    dispositions=[
                        {"instance_id": str(instance.id), "disposition": "retain"}
                    ],
                ),
            )
            await session.refresh(run)
            await service.apply_plan(
                run_id=run.id,
                plan_id=retained.id,
                expected_revision=run.revision,
                expected_control_epoch=run.control_epoch,
            )
            await session.commit()
            assert (
                await session.scalar(select(func.count(DirectorBusinessFlowInstance.id)))
                == 1
            )
            assert (
                await session.scalar(select(func.count(DirectorBusinessFlowStep.id)))
                == 2
            )

        # An unknown submission keeps the step's only slot.
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["owner_id"],
                workspace_id=ids["workspace_id"],
                project_id=ids["project_id"],
            )
            owner = await session.get(User, ids["owner_id"])
            project = await session.get(Project, ids["project_id"])
            assert owner is not None and project is not None
            flows = BusinessFlowService(
                session, actor=owner, project=project, registry=REGISTRY,
            )
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
                    action_kind="production",
                    action_key="submit",
                    command_key=f"flow:{step.id}:1",
                    status="unknown_submission",
                    unresolved_external=True,
                )
            )
            await session.commit()
            progress = await flows.progress(ids["run_id"])
            assert progress["unresolved_external_count"] == 1


WORKER_FLOW = BusinessFlowDefinition(
    flow_key="worker_probe",
    definition_key="worker_probe",
    definition_version="1",
    state_schema_version="business-flow-state-v1",
    scope_type="project",
    steps=(FlowStepSpec(step_key="read_project", tool_name="project_get", action_kind="read"),),
    completion_rule_ids=("all_required_steps_succeeded",),
    resume_rule_id="retain_completed_steps",
    graph_entrypoint="worker_probe",
)
WORKER_REGISTRY = BusinessFlowDefinitionRegistry((WORKER_FLOW,))


async def test_worker_advances_flow_through_real_tool_registry():
    async with flow_database() as (name, _engine, factory):
        async with factory() as session:
            owner, workspace, project, _other, thread, turn, item = await _seed(session)
            session.info["selected_workspace_id"] = workspace.id
            service = MasterRunService(
                session, actor=owner, project=project, flow_registry=WORKER_REGISTRY,
            )
            run = await service.create_for_origin_turn(
                turn_id=turn.id, goal="整理古城灯会资料",
            )
            plan = await service.append_plan(
                run_id=run.id,
                decision_ref=item.id,
                plan_data=_plan(
                    run,
                    flows=[
                        {
                            "flow_key": "worker_probe",
                            "definition_key": "worker_probe",
                            "definition_version": "1",
                            "scope_type": "project",
                            "scope_entity_id": str(project.id),
                            "input": {"mark": "worker"},
                        }
                    ],
                ),
                created_by_turn_id=turn.id,
            )
            await session.refresh(run)
            await service.apply_plan(
                run_id=run.id,
                plan_id=plan.id,
                expected_revision=run.revision,
                expected_control_epoch=run.control_epoch,
            )
            await session.commit()
            instance_id = await session.scalar(select(DirectorBusinessFlowInstance.id))
        assert instance_id is not None

        app_engine = create_async_engine(
            _async_url(name),
            connect_args={"server_settings": {"role": "dramaforge_app"}},
        )
        app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
        try:
            from app.director.business_flow_worker import execute_business_flow

            result = await execute_business_flow(
                app_factory, instance_id=instance_id, registry=WORKER_REGISTRY
            )
            assert result["status"] == "succeeded"
            async with factory() as session:
                instance = await session.get(DirectorBusinessFlowInstance, instance_id)
                assert instance is not None and instance.status == "succeeded"
                attempt = await session.scalar(select(DirectorBusinessFlowStepAttempt))
                assert attempt is not None and attempt.status == "succeeded"
                assert attempt.receipt_ref is not None
                assert attempt.receipt_ref["ok"] is True
                assert attempt.action_key == "project_get"
        finally:
            await app_engine.dispose()


async def test_populated_flow_history_blocks_downgrade():
    name = f"dramaforge_flows_mig_{uuid4().hex[:8]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        assert migration(name, "upgrade", "head").returncode == 0
        await _apply_first_plan(factory)
        refused = migration(name, "downgrade", "20261118_0106")
        assert refused.returncode != 0
        assert "BUSINESS_FLOWS_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE" in refused.stderr
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == alembic_head()
    finally:
        await engine.dispose()
        await _drop_database(name)
