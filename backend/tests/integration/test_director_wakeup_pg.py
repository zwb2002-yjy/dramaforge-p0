"""Independent director transaction failure cannot affect accepted production."""

import asyncio
import os
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.access.models import ProjectCreativeProfile
from app.contracts.production_commands import ExecutionBody
from app.director.business_checkpoints import DirectorBusinessCheckpoints
from app.director.inbox import receive_production_event
from app.director.inbox_models import DirectorWakeup
from app.director.turn_models import DirectorTurn
from app.director.wakeup import process_director_wakeup
from app.director.wakeup_replay import replay_failed_wakeup
from app.events.models import OutboxEvent
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.production.application.commands import ProductionCommands
from app.production.workbench_execution import WorkbenchExecutionService
from app.shared.db import set_rls_context
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _input, _seed, _seed_video_shot


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", [
    "direct", "dead_letter", "process_kill", pytest.param("arq", marks=pytest.mark.skipif(
        not os.environ.get("TEST_DIRECTOR_REDIS_URL"), reason="isolated Redis required",
    )),
    "late_completed", "late_cached", "late_cancelled", "late_completed_after_cancel",
])
async def test_director_failure_rolls_back_only_wakeup_and_retries_once(monkeypatch, delivery):
    dbname = f"dramaforge_d2_wakeup_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        admin = async_sessionmaker(engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin() as session:
            project, binding, actor = await _seed(session)
            shot, _artifact = await _seed_video_shot(session, project=project, user=actor)
            session.add(ProjectCreativeProfile(
                project_id=project.id, start_type="FREE", director_autonomy="AUTO",
            ))
            await session.commit()
            command = _input(project_id=project.id, shot_id=shot.id,
                             requested_binding_id=binding.id, expected_shot_version=shot.version)
            plan = await WorkbenchExecutionService(session, user_id=actor.id).build_plan(
                project=project, execution_input=command,
            )
            receipt = await ProductionCommands(session).submit_user_execution(
                actor=actor, project_id=project.id, shot_id=shot.id, command_key="independent",
                body=ExecutionBody(
                    **command.model_dump(exclude={"project_id", "shot_id", "shot_experiment_id"}),
                    plan_fingerprint=plan.plan_fingerprint,
                    accepted_approximations=plan.accepted_approximations,
                ),
            )
            await session.commit()
            event = await session.scalar(select(OutboxEvent).where(
                OutboxEvent.topic == "production.facts.v1",
            ))
            event_id = event.event_id
        if delivery.startswith("late_"):
            terminal_status = delivery.removeprefix("late_")
            async with factory() as session:
                await set_rls_context(session, user_id=actor.id, workspace_id=project.workspace_id,
                                      project_id=project.id)
                run = await session.get(NodeRun, receipt.node_run_id)
                if terminal_status != "cancelled":
                    artifact = Artifact(
                        project_id=project.id, artifact_type="video", storage_state="available",
                        object_key=f"test/{uuid4().hex}.mp4", content_hash="f" * 64,
                        mime_type="video/mp4", byte_size=1,
                    )
                    session.add(artifact)
                    await session.flush()
                    run.result_artifact_id = artifact.id
                    if terminal_status == "cached":
                        source = NodeRun(
                            project_id=project.id, graph_version_id=run.graph_version_id,
                            graph_node_id=run.graph_node_id, attempt_no=2,
                            idempotency_key=f"cache-source:{uuid4().hex}",
                            input_hash=run.input_hash, input_snapshot=run.input_snapshot,
                            status="completed", result_artifact_id=artifact.id,
                            created_by=actor.id,
                        )
                        session.add(source)
                        await session.flush()
                        run.reused_from_run_id = source.id
                run.status = terminal_status
                await session.commit()
            async with admin() as session:
                changed = (await session.scalars(select(OutboxEvent).where(
                    OutboxEvent.payload["notice"]["kind"].as_string() == "execution_changed",
                ))).one()
                changed_id = changed.event_id
            # Deliver the terminal fact before the original acceptance.
            for notice_id in (changed_id, event_id, changed_id, event_id):
                async with factory() as session:
                    await set_rls_context(session, user_id=actor.id,
                                          workspace_id=project.workspace_id, project_id=project.id)
                    received = await receive_production_event(
                        session, project_id=project.id, event_id=notice_id,
                    )
                    await session.commit()
                await process_director_wakeup(factory, inbox_id=received)
            async with admin() as session:
                turn = (await session.scalars(select(DirectorTurn))).one()
                assert turn.status == "awaiting_user"
                assert turn.response_summary["coordination"]["current_action"]["action"] == (
                    "review_execution_failure" if terminal_status == "cancelled"
                    else "confirm_formal_candidate"
                )
                assert await session.scalar(select(func.count()).select_from(
                    ProviderOperation,
                )) == 0
                assert (await session.get(NodeRun, receipt.node_run_id)).status == terminal_status
            return
        async with factory() as session:
            await set_rls_context(session, user_id=actor.id, workspace_id=project.workspace_id,
                                  project_id=project.id)
            inbox_id = await receive_production_event(session, project_id=project.id,
                                                       event_id=event_id)
            await session.commit()
        original = DirectorBusinessCheckpoints.reconcile_business_fact

        async def fail_after_tracking(*args, **kwargs):
            raise RuntimeError("Injected director failure before wakeup completion")

        monkeypatch.setattr(
            DirectorBusinessCheckpoints, "reconcile_business_fact", fail_after_tracking,
        )
        assert not await process_director_wakeup(factory, inbox_id=inbox_id)
        async with admin() as session:
            assert (await session.get(NodeRun, receipt.node_run_id)).status == "queued"
            failed = await session.get(DirectorWakeup, inbox_id)
            assert failed.completed_at is None and failed.attempt_count == 1
            assert failed.last_error == "RuntimeError"
            assert failed.next_attempt_at > datetime.now(UTC)
            assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 0
        assert not await process_director_wakeup(factory, inbox_id=inbox_id)
        if delivery == "dead_letter":
            for attempt in range(2, 6):
                # Advance only this fixture's retry due time; assert real
                # production code persists backoff and the retry limit.
                async with admin() as session:
                    pending = await session.get(DirectorWakeup, inbox_id)
                    pending.next_attempt_at = datetime.now(UTC)
                    await session.commit()
                assert not await process_director_wakeup(factory, inbox_id=inbox_id)
                async with admin() as session:
                    pending = await session.get(DirectorWakeup, inbox_id)
                    assert pending.attempt_count == attempt
            async with admin() as session:
                pending = await session.get(DirectorWakeup, inbox_id)
                assert pending.dead_letter_at is not None and pending.completed_at is None
                assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 0
                assert (await session.get(NodeRun, receipt.node_run_id)).status == "queued"
            assert not await process_director_wakeup(factory, inbox_id=inbox_id)
            async with admin() as session:
                pending = await session.get(DirectorWakeup, inbox_id)
                failed_at = pending.dead_letter_at
                assert await replay_failed_wakeup(
                    session, actor=actor, project_id=project.id, inbox_id=inbox_id,
                    expected_dead_letter_at=failed_at,
                )
                await session.commit()
            async with admin() as session:
                assert not await replay_failed_wakeup(
                    session, actor=actor, project_id=project.id, inbox_id=inbox_id,
                    expected_dead_letter_at=failed_at,
                )
                await session.commit()
            monkeypatch.setattr(DirectorBusinessCheckpoints, "reconcile_business_fact", original)
            assert await process_director_wakeup(factory, inbox_id=inbox_id)
            return
        async with admin() as session:
            pending = await session.get(DirectorWakeup, inbox_id)
            pending.next_attempt_at = datetime.now(UTC)
            await session.commit()
        monkeypatch.setattr(DirectorBusinessCheckpoints, "reconcile_business_fact", original)
        if delivery == "direct":
            results = await asyncio.gather(
                process_director_wakeup(factory, inbox_id=inbox_id),
                process_director_wakeup(factory, inbox_id=inbox_id),
            )
            assert sorted(results) == [False, True]
        elif delivery == "process_kill":
            child_source = '''
import asyncio, os
from uuid import UUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.shared.model_registry import load_all_models
from app.director.business_checkpoints import DirectorBusinessCheckpoints
from app.director.wakeup import process_director_wakeup
load_all_models()
async def paused(*args, **kwargs):
    print("checkpoint-ready", flush=True)
    await asyncio.Event().wait()
DirectorBusinessCheckpoints.reconcile_business_fact = paused
async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"],
        connect_args={"server_settings": {"role": "dramaforge_app"}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await process_director_wakeup(factory, inbox_id=UUID(os.environ["TEST_WAKEUP_ID"]))
asyncio.run(main())
'''
            child = await asyncio.create_subprocess_exec(
                sys.executable, "-c", child_source,
                env={**os.environ, "DATABASE_URL": _async_url(dbname),
                     "TEST_WAKEUP_ID": str(inbox_id)},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                ready = await asyncio.wait_for(child.stdout.readline(), 15)
                assert ready.strip() == b"checkpoint-ready"
                child.kill()
                await asyncio.wait_for(child.wait(), 10)
                assert child.returncode != 0
            finally:
                if child.returncode is None:
                    child.kill()
                    await child.wait()
            async with admin() as session:
                assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 0
                pending = await session.get(DirectorWakeup, inbox_id)
                assert pending.completed_at is None and pending.attempt_count == 1
                assert (await session.get(NodeRun, receipt.node_run_id)).status == "queued"
            assert await process_director_wakeup(factory, inbox_id=inbox_id)
        else:
            from app.workers import director
            from arq import create_pool
            from arq.connections import RedisSettings
            from arq.worker import Worker

            queue = f"arq:director:test:{uuid4().hex}"
            monkeypatch.setattr(director, "QUEUE_NAME", queue)
            monkeypatch.setattr(director, "get_session_factory", lambda: factory)
            redis = await create_pool(RedisSettings.from_dsn(os.environ["TEST_DIRECTOR_REDIS_URL"]))

            class UnavailableIntake:
                async def poll_once(self):
                    raise ConnectionError("Intake down; committed wakeup must still run")

            worker = Worker(
                [director.execute_director_wakeup], redis_pool=redis, queue_name=queue,
                burst=True, handle_signals=False, poll_delay=0.01, keep_result=0,
            )
            try:
                ctx = {"redis": redis, "director_consumer": UnavailableIntake()}
                assert await director.dispatch_director_wakeups(ctx) == 1
                assert await director.dispatch_director_wakeups(ctx) == 1
                assert await redis.zcard(queue) == 1
                await asyncio.wait_for(worker.async_run(), 20)
                assert worker.jobs_complete == 1 and worker.jobs_failed == 0
                assert await director.dispatch_director_wakeups(ctx) == 0
            finally:
                if os.name == "nt":
                    # Burst execution has returned; no job remains live. Arq
                    # close() references Unix-only SIGUSR1 on this platform.
                    # Release this test's pool and health key explicitly.
                    await asyncio.gather(*worker.tasks.values(), return_exceptions=True)
                    await redis.delete(worker.health_check_key)
                    await redis.aclose(close_connection_pool=True)
                else:
                    await worker.close()
        async with admin() as session:
            assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 1
            assert (await session.get(DirectorWakeup, inbox_id)).completed_at is not None
            assert await session.scalar(select(func.count()).select_from(ProviderOperation)) == 0
        if delivery == "direct":
            async with factory() as session:
                await set_rls_context(session, user_id=actor.id, workspace_id=project.workspace_id,
                                      project_id=project.id)
                run = await session.get(NodeRun, receipt.node_run_id)
                run.status = "failed"
                await session.flush()
                await session.rollback()
            async with admin() as session:
                assert (await session.get(NodeRun, receipt.node_run_id)).status == "queued"
                assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
                    OutboxEvent.payload["notice"]["kind"].as_string() == "execution_changed",
                )) == 0
            async with factory() as session:
                await set_rls_context(session, user_id=actor.id, workspace_id=project.workspace_id,
                                      project_id=project.id)
                run = await session.get(NodeRun, receipt.node_run_id)
                run.status = "failed"
                await session.commit()
            async with admin() as session:
                notices = list((await session.scalars(select(OutboxEvent).where(
                    OutboxEvent.payload["notice"]["kind"].as_string() == "execution_changed",
                ))).all())
                assert len(notices) == 1
                changed_id = notices[0].event_id
                next_inbox = await receive_production_event(
                    session, project_id=project.id, event_id=changed_id,
                )
                await session.commit()
            assert await process_director_wakeup(factory, inbox_id=next_inbox)
            async with admin() as session:
                turn = await session.scalar(select(DirectorTurn))
                assert turn.status == "awaiting_user" and turn.wait_reason == "execution_failed"
    finally:
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)
