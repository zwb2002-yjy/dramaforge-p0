"""D5 real Proposal -> durable wakeup -> LangGraph decision flow."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from app.access.models import ProjectCreativeProfile
from app.config import Settings
from app.contracts.director_runtime import ResumeSignal, RuntimeScope, StopRequest
from app.contracts.domain_events import ExecutionChanged, FormalSelected
from app.contracts.production_commands import ExecutionBody
from app.director.assistant_models import DirectorThread
from app.director.inbox import receive_production_event
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.proposal_service import PartialApplyInput, ProposalDecision, ProposalService
from app.director.runtime.control import DirectorRuntimeControlService
from app.director.runtime.models import DirectorRuntimeControl, DirectorRuntimeWakeup
from app.director.runtime.start import DirectorRuntimeStartService
from app.director.runtime.wakeups import DirectorRuntimeWakeupService
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.director.wakeup import apply_director_wakeup
from app.events.models import EventLog
from app.execution.models import Artifact, NodeRun
from app.production.application.events import append_production_notice
from app.production.command_models import ProductionCommandAuthorization
from app.production.workbench_execution import WorkbenchExecutionService
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    DB_PASSWORD,
    DB_USER,
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
    _host,
    _port,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _input, _seed, _seed_video_shot

CHECKPOINT_ROLE = "dramaforge_director_checkpoint"
CHECKPOINT_PASSWORD = "d5-checkpoint-flow-password"


@pytest.fixture(scope="module")
def event_loop_policy():
    if os.name == "nt":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


def _admin_dsn(dbname: str) -> str:
    return f"postgresql://{DB_USER}:{DB_PASSWORD}@{_host()}:{_port()}/{dbname}"


def _checkpoint_dsn(dbname: str) -> str:
    return (
        f"postgresql://{CHECKPOINT_ROLE}:{CHECKPOINT_PASSWORD}"
        f"@{_host()}:{_port()}/{dbname}"
    )


@pytest.mark.asyncio
async def test_stop_before_first_checkpoint_settles_start_and_stop_wakeups(
    monkeypatch: pytest.MonkeyPatch,
):
    dbname = f"dramaforge_d5_prestart_stop_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin_dsn = _admin_dsn(dbname)
    admin_engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
            await admin.execute(
                f"ALTER ROLE {CHECKPOINT_ROLE} LOGIN PASSWORD '{CHECKPOINT_PASSWORD}'"
            )
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin_factory() as session:
            project, _binding, actor = await _seed(session)
            await session.commit()
        settings = Settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url=_checkpoint_dsn(dbname),
        )
        scope = RuntimeScope(
            workspace_id=project.workspace_id,
            project_id=project.id,
            actor_id=actor.id,
        )
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            thread = DirectorThread(
                project_id=project.id,
                scope_type="project",
                scope_entity_id=project.id,
                title="Pre-checkpoint stop",
                created_by=actor.id,
            )
            session.add(thread)
            await session.flush()
            proposal = DirectorProposal(
                project_id=project.id,
                thread_id=thread.id,
                scope_type="project",
                scope_entity_id=project.id,
                created_by=actor.id,
            )
            session.add(proposal)
            await session.flush()
            session.add(DirectorProposalItem(
                proposal_id=proposal.id,
                project_id=project.id,
                command="story.set_script_document",
                payload={
                    "filename": "stopped-before-start.md",
                    "content_hash": "e" * 64,
                    "raw_text": "This command must never be applied.",
                    "format": "md",
                },
            ))
            turn, start_wakeup = await DirectorRuntimeStartService(
                session, settings=settings,
            ).accept(
                project=project,
                actor=actor,
                proposal_id=proposal.id,
                authorization_ref=None,
                request_key="runtime:precheckpoint-stop",
                max_steps=6,
            )
            assert turn.runtime_execution_id is not None
            stop_request = StopRequest(
                scope=scope,
                turn_id=turn.id,
                request_id=uuid4(),
                expected_revision=1,
            )
            await DirectorRuntimeControlService(session).request_stop(
                project_id=project.id,
                runtime_execution_id=turn.runtime_execution_id,
            )
            stop_wakeup = await DirectorRuntimeWakeupService(session).enqueue_stop(
                stop_request,
                runtime_execution_id=turn.runtime_execution_id,
            )
            await DirectorTurnService(session).stop(
                project_id=project.id,
                turn_id=turn.id,
                expected_revision=turn.revision,
            )
            await session.commit()

        from app.workers import director

        monkeypatch.setattr(director, "get_session_factory", lambda: factory)
        monkeypatch.setattr(director, "get_settings", lambda: settings)
        assert await director.execute_director_runtime_wakeup({}, str(stop_wakeup.id))
        assert await director.execute_director_runtime_wakeup({}, str(start_wakeup.id))

        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            stored = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert stored.status == "cancelled"
            assert stored.wait_reason == "user_stopped"
            assert stored.runtime_revision is None
            control = await session.get(DirectorRuntimeControl, turn.runtime_execution_id)
            assert control is not None and control.status == "stopped"
            wakeups = list((await session.scalars(select(DirectorRuntimeWakeup).where(
                DirectorRuntimeWakeup.runtime_execution_id == turn.runtime_execution_id,
            ))).all())
            assert len(wakeups) == 2
            assert all(row.completed_at is not None for row in wakeups)
            assert all(row.last_error is None for row in wakeups)
            assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()
        try:
            async with await psycopg.AsyncConnection.connect(
                admin_dsn, autocommit=True,
            ) as admin:
                await admin.execute(
                    f"ALTER ROLE {CHECKPOINT_ROLE} NOLOGIN PASSWORD NULL"
                )
        finally:
            await _drop_database(dbname)


@pytest.mark.asyncio
async def test_new_runtime_turn_completes_from_persisted_proposal_decision_event(
    monkeypatch: pytest.MonkeyPatch,
):
    dbname = f"dramaforge_d5_flow_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin_dsn = _admin_dsn(dbname)
    admin_engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
            await admin.execute(
                f"ALTER ROLE {CHECKPOINT_ROLE} LOGIN PASSWORD '{CHECKPOINT_PASSWORD}'"
            )
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin_factory() as session:
            project, _binding, actor = await _seed(session)
            await session.commit()
        settings = Settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url=_checkpoint_dsn(dbname),
        )
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            thread = DirectorThread(
                project_id=project.id,
                scope_type="project",
                scope_entity_id=project.id,
                title="Project proposal",
                created_by=actor.id,
            )
            session.add(thread)
            await session.flush()
            proposal = DirectorProposal(
                project_id=project.id,
                thread_id=thread.id,
                scope_type="project",
                scope_entity_id=project.id,
                created_by=actor.id,
            )
            session.add(proposal)
            await session.flush()
            item = DirectorProposalItem(
                proposal_id=proposal.id,
                project_id=project.id,
                command="story.set_script_document",
                payload={
                    "filename": "runtime-story.md",
                    "content_hash": "d" * 64,
                    "raw_text": "A bounded Director proposal.",
                    "format": "md",
                },
            )
            session.add(item)
            turn, start_wakeup = await DirectorRuntimeStartService(
                session, settings=settings,
            ).accept(
                project=project,
                actor=actor,
                proposal_id=proposal.id,
                authorization_ref=None,
                request_key="runtime:proposal:one",
                max_steps=6,
            )
            await session.commit()

        from app.workers import director

        monkeypatch.setattr(director, "get_session_factory", lambda: factory)
        monkeypatch.setattr(director, "get_settings", lambda: settings)
        redis_url = os.environ.get("TEST_DIRECTOR_REDIS_URL")
        if redis_url:
            from arq import create_pool
            from arq.connections import RedisSettings
            from arq.worker import Worker

            queue = f"arq:director:d5:{uuid4().hex}"
            monkeypatch.setattr(director, "QUEUE_NAME", queue)
            redis = await create_pool(RedisSettings.from_dsn(redis_url))

            class UnavailableIntake:
                async def poll_once(self):
                    raise ConnectionError("intake intentionally unavailable")

            worker = Worker(
                [director.execute_director_runtime_wakeup],
                redis_pool=redis,
                queue_name=queue,
                burst=True,
                handle_signals=False,
                poll_delay=0.01,
                keep_result=0,
            )
            try:
                ctx = {"redis": redis, "director_consumer": UnavailableIntake()}
                assert await director.dispatch_director_wakeups(ctx) == 1
                assert await director.dispatch_director_wakeups(ctx) == 1
                assert await redis.zcard(queue) == 1
                await asyncio.wait_for(worker.async_run(), 20)
                assert worker.jobs_complete == 1 and worker.jobs_failed == 0
            finally:
                if os.name == "nt":
                    await asyncio.gather(*worker.tasks.values(), return_exceptions=True)
                    await redis.delete(worker.health_check_key)
                    await redis.aclose(close_connection_pool=True)
                else:
                    await worker.close()
        else:
            assert await director.execute_director_runtime_wakeup({}, str(start_wakeup.id))
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            waiting = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert waiting.status == "awaiting_user"
            assert waiting.wait_reason == "proposal_decision"
            result = await ProposalService(session, actor=actor).partial_apply(
                project=project,
                proposal_id=proposal.id,
                apply_input=PartialApplyInput(decisions=[
                    ProposalDecision(item_id=item.id, decision="accepted"),
                ]),
            )
            assert result.accepted == [item.id]
            events = list((await session.scalars(select(EventLog).where(
                EventLog.project_id == project.id,
            ).order_by(EventLog.occurred_at.desc(), EventLog.id.desc()))).all())
            decision_event = next(
                event for event in events
                if (event.payload or {}).get("notice", {}).get("kind") == "proposal_decided"
            )
            inbox_id = await receive_production_event(
                session,
                project_id=project.id,
                event_id=decision_event.event_id,
            )
            assert await apply_director_wakeup(session, inbox_id=inbox_id)
            runtime_wakeup = await session.scalar(select(DirectorRuntimeWakeup).where(
                DirectorRuntimeWakeup.runtime_execution_id == turn.runtime_execution_id,
                DirectorRuntimeWakeup.kind == "resume",
            ))
            assert runtime_wakeup is not None
            runtime_wakeup_id = runtime_wakeup.id
            await session.commit()

        assert await director.execute_director_runtime_wakeup({}, str(runtime_wakeup_id))
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            completed = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert completed.status == "completed"
            assert completed.wait_reason == "proposal_applied"
            assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0

            detached = DirectorTurn(
                workspace_id=project.workspace_id,
                project_id=project.id,
                actor_id=actor.id,
                scope_type="shot",
                scope_entity_id=uuid4(),
                request_key="runtime:detached-shot:one",
                context_hash="e" * 64,
                input_versions={"shot": 1},
                intent_snapshot={"user_instruction": "Keep the camera static"},
                model_resolution={"model_id": "test/director"},
                transport_status="succeeded",
                request_summary={"task": "shot_director_suggestion", "max_steps": 4},
                response_summary={},
                output_hash="f" * 64,
                output_snapshot={
                    "base_shot_version": 1,
                    "suggested_image_prompt": "static frame",
                    "suggested_video_prompt": "static camera",
                    "suggested_director_state": {"camera": "static"},
                    "change_summary": "Keep the camera static",
                },
                status="awaiting_user",
                wait_reason="proposal_decision",
                step_count=1,
            )
            session.add(detached)
            await session.flush()
            detached_start = await DirectorRuntimeStartService(
                session, settings=settings,
            ).accept_existing_detached_turn(
                project=project,
                actor=actor,
                turn=detached,
                created=True,
            )
            assert detached_start is not None
            detached_start_id = detached_start.id
            await session.commit()

        assert await director.execute_director_runtime_wakeup({}, str(detached_start_id))
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            waiting_detached = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=detached.id,
            )
            assert waiting_detached.runtime_revision is not None
            assert waiting_detached.runtime_execution_id is not None
            assert waiting_detached.proposal_id is None
            decided = await DirectorTurnService(session).record_user_decision(
                project_id=project.id,
                turn_id=detached.id,
                expected_revision=waiting_detached.revision,
                decision="reject",
                accepted_operation_indices=[],
            )
            assert decided.status == "awaiting_user"
            detached_signal = ResumeSignal(
                scope=RuntimeScope(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    actor_id=actor.id,
                ),
                turn_id=detached.id,
                signal_id=uuid4(),
                reason="user_decision",
                reference_id=detached.id,
                expected_revision=waiting_detached.runtime_revision,
            )
            detached_resume = await DirectorRuntimeWakeupService(session).enqueue_resume(
                detached_signal,
                runtime_execution_id=waiting_detached.runtime_execution_id,
            )
            detached_resume_id = detached_resume.id
            await session.commit()

        assert await director.execute_director_runtime_wakeup({}, str(detached_resume_id))
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            completed_detached = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=detached.id,
            )
            assert completed_detached.status == "completed"
            assert completed_detached.wait_reason == "proposal_rejected"
            assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()
        try:
            async with await psycopg.AsyncConnection.connect(
                admin_dsn, autocommit=True,
            ) as admin:
                await admin.execute(
                    f"ALTER ROLE {CHECKPOINT_ROLE} NOLOGIN PASSWORD NULL"
                )
        finally:
            await _drop_database(dbname)


@pytest.mark.asyncio
async def test_runtime_submits_only_the_persisted_production_authorization(
    monkeypatch: pytest.MonkeyPatch,
):
    dbname = f"dramaforge_d5_command_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin_dsn = _admin_dsn(dbname)
    admin_engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
            await admin.execute(
                f"ALTER ROLE {CHECKPOINT_ROLE} LOGIN PASSWORD '{CHECKPOINT_PASSWORD}'"
            )
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin_factory() as session:
            project, binding, actor = await _seed(session)
            shot, _keyframe = await _seed_video_shot(
                session, project=project, user=actor,
            )
            session.add(ProjectCreativeProfile(
                project_id=project.id,
                start_type="FREE",
                director_autonomy="AUTO",
            ))
            await session.commit()
        settings = Settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url=_checkpoint_dsn(dbname),
        )
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            execution_input = _input(
                project_id=project.id,
                shot_id=shot.id,
                requested_binding_id=binding.id,
                expected_shot_version=shot.version,
            )
            plan = await WorkbenchExecutionService(
                session, user_id=actor.id,
            ).build_plan(project=project, execution_input=execution_input)
            body = ExecutionBody(
                **execution_input.model_dump(
                    exclude={"project_id", "shot_id", "shot_experiment_id"},
                ),
                plan_fingerprint=plan.plan_fingerprint,
                accepted_approximations=plan.accepted_approximations,
            )
            decision_id = uuid4()
            expiry = datetime.now(UTC) + timedelta(hours=1)
            from app.api.v1 import director as director_api

            monkeypatch.setattr(director_api, "get_settings", lambda: settings)
            delegation_body = director_api.DirectorRuntimeDelegationBody(
                decision_id=decision_id,
                execution=body,
                authorization_expires_at=expiry,
                max_steps=6,
            )
            accepted = await director_api.delegate_shot_execution_to_director(
                project_id=project.id,
                shot_id=shot.id,
                body=delegation_body,
                user=actor,
                session=session,
                _csrf="controlled",
            )
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            replay = await director_api.delegate_shot_execution_to_director(
                project_id=project.id,
                shot_id=shot.id,
                body=delegation_body,
                user=actor,
                session=session,
                _csrf="controlled",
            )
            assert replay.id == accepted.id
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            turn = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=accepted.id,
            )
            assert turn.runtime_execution_id is not None
            start_wakeup = await session.scalar(select(DirectorRuntimeWakeup).where(
                DirectorRuntimeWakeup.runtime_execution_id == turn.runtime_execution_id,
                DirectorRuntimeWakeup.kind == "start",
            ))
            assert start_wakeup is not None
            authorization_id = await session.scalar(
                select(ProductionCommandAuthorization.id).where(
                    ProductionCommandAuthorization.project_id == project.id,
                    ProductionCommandAuthorization.command_key == f"approved:{decision_id}",
                )
            )
            assert authorization_id is not None
            await session.commit()

        from app.workers import director

        monkeypatch.setattr(director, "get_session_factory", lambda: factory)
        monkeypatch.setattr(director, "get_settings", lambda: settings)
        assert await director.execute_director_runtime_wakeup({}, str(start_wakeup.id))
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            submitted = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            grant = await session.get(ProductionCommandAuthorization, authorization_id)
            runs = list((await session.scalars(select(NodeRun))).all())
            assert submitted.status == "awaiting_execution"
            assert submitted.dispatched_command_key == f"approved:{decision_id}"
            assert len(submitted.node_run_ids) == 1
            assert len(runs) == 2  # seeded keyframe plus the one accepted video run
            assert grant is not None and grant.status == "accepted"
            assert str(grant.node_run_id) == str(submitted.node_run_ids[0])

            submitted_run_id = UUID(str(submitted.node_run_ids[0]))
            submitted_run = await session.get(NodeRun, submitted_run_id)
            assert submitted_run is not None
            artifact = Artifact(
                project_id=project.id,
                artifact_type="video",
                storage_state="available",
                object_key=f"test/{uuid4().hex}.mp4",
                content_hash="f" * 64,
                mime_type="video/mp4",
                byte_size=1,
            )
            session.add(artifact)
            await session.flush()
            submitted_run.result_artifact_id = artifact.id
            submitted_run.status = "completed"
            terminal_event_id = await append_production_notice(
                session,
                project_id=project.id,
                actor_id=actor.id,
                notice=ExecutionChanged(
                    shot_id=shot.id,
                    node_run_id=submitted_run_id,
                ),
            )
            current_shot = await session.get(type(shot), shot.id)
            assert current_shot is not None
            current_shot.formal_video_artifact_id = artifact.id
            current_shot.version += 1
            formal_event_id = await append_production_notice(
                session,
                project_id=project.id,
                actor_id=actor.id,
                notice=FormalSelected(
                    shot_id=shot.id,
                    shot_version=current_shot.version,
                    artifact_id=artifact.id,
                    stage="video",
                ),
            )
            await session.commit()

        # Deliver Formal first. It stays canonical but must not enter a graph
        # that is still interrupted on the production-fact checkpoint.
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            formal_inbox_id = await receive_production_event(
                session,
                project_id=project.id,
                event_id=formal_event_id,
            )
            await session.commit()
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            assert await apply_director_wakeup(session, inbox_id=formal_inbox_id)
            assert await session.scalar(
                select(func.count()).select_from(DirectorRuntimeWakeup).where(
                    DirectorRuntimeWakeup.runtime_execution_id == turn.runtime_execution_id,
                    DirectorRuntimeWakeup.kind == "resume",
                )
            ) == 0
            await session.commit()

        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            inbox_id = await receive_production_event(
                session,
                project_id=project.id,
                event_id=terminal_event_id,
            )
            await session.commit()
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            assert await apply_director_wakeup(session, inbox_id=inbox_id)
            terminal_wakeup = await session.scalar(
                select(DirectorRuntimeWakeup).where(
                    DirectorRuntimeWakeup.runtime_execution_id
                    == turn.runtime_execution_id,
                    DirectorRuntimeWakeup.kind == "resume",
                )
            )
            assert terminal_wakeup is not None
            await session.commit()

        assert await director.execute_director_runtime_wakeup(
            {}, str(terminal_wakeup.id),
        )
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            waiting_confirmation = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert waiting_confirmation.status == "awaiting_user"
            assert waiting_confirmation.wait_reason == "confirm_candidate"
            assert await session.scalar(select(func.count()).select_from(NodeRun)) == 2

        # Reconciliation now observes the already committed Formal fact and
        # schedules the next signal without replaying production.
        from app.workers import jobs

        monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
        reconciliation = await jobs.reconcile_waiting_director_turns({})
        assert reconciliation["reconciled"] >= 1
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            formal_wakeup = await session.scalar(
                select(DirectorRuntimeWakeup).where(
                    DirectorRuntimeWakeup.runtime_execution_id == turn.runtime_execution_id,
                    DirectorRuntimeWakeup.kind == "resume",
                    DirectorRuntimeWakeup.completed_at.is_(None),
                    DirectorRuntimeWakeup.dead_letter_at.is_(None),
                )
            )
            assert formal_wakeup is not None
            await session.commit()
        assert await director.execute_director_runtime_wakeup({}, str(formal_wakeup.id))
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            completed = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert completed.status == "completed"
            assert completed.wait_reason == "candidate_confirmed"
            assert await session.scalar(select(func.count()).select_from(NodeRun)) == 2

        async with admin_factory() as session:
            profile = await session.scalar(select(ProjectCreativeProfile).where(
                ProjectCreativeProfile.project_id == project.id,
            ))
            assert profile is not None
            profile.director_autonomy = "ASSIST"
            profile.version += 1
            await session.commit()
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            denied_decision = uuid4()
            with pytest.raises(ConflictError) as denied:
                await director_api.delegate_shot_execution_to_director(
                    project_id=project.id,
                    shot_id=shot.id,
                    body=director_api.DirectorRuntimeDelegationBody(
                        decision_id=denied_decision,
                        execution=body,
                        authorization_expires_at=datetime.now(UTC) + timedelta(minutes=15),
                        max_steps=6,
                    ),
                    user=actor,
                    session=session,
                    _csrf="controlled",
                )
            assert denied.value.details["code"] == "DIRECTOR_AUTO_REQUIRED"
            await session.rollback()
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            assert await session.scalar(select(func.count()).select_from(
                ProductionCommandAuthorization,
            ).where(
                ProductionCommandAuthorization.command_key == f"approved:{denied_decision}",
            )) == 0
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()
        try:
            async with await psycopg.AsyncConnection.connect(
                admin_dsn, autocommit=True,
            ) as admin:
                await admin.execute(
                    f"ALTER ROLE {CHECKPOINT_ROLE} NOLOGIN PASSWORD NULL"
                )
        finally:
            await _drop_database(dbname)
