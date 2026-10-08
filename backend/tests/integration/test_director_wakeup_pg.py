"""Director inbox wakeup failure cannot affect accepted production."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.contracts.production_commands import ExecutionBody
from app.director.inbox import receive_production_event
from app.director.inbox_models import DirectorWakeup
from app.director.turn_models import DirectorTurn
import app.director.wakeup as director_wakeup
from app.director.wakeup_replay import replay_failed_wakeup
from app.events.models import OutboxEvent
from app.execution.models import NodeRun
from app.production.application.commands import ProductionCommands
from app.production.workbench_execution import WorkbenchExecutionService
from app.shared.db import set_rls_context
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _input, _seed, _seed_video_shot


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["direct", "dead_letter", "process_kill"])
async def test_director_wakeup_failure_is_isolated_and_replayable(monkeypatch, delivery):
    dbname = f"dramaforge_d2_wakeup_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname),
        connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        admin = async_sessionmaker(engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin() as session:
            project, binding, actor = await _seed(session)
            shot, _artifact = await _seed_video_shot(session, project=project, user=actor)
            await session.commit()
            command = _input(
                project_id=project.id,
                shot_id=shot.id,
                requested_binding_id=binding.id,
                expected_shot_version=shot.version,
            )
            plan = await WorkbenchExecutionService(session, user_id=actor.id).build_plan(
                project=project,
                execution_input=command,
            )
            receipt = await ProductionCommands(session).submit_user_execution(
                actor=actor,
                project_id=project.id,
                shot_id=shot.id,
                command_key="independent",
                body=ExecutionBody(
                    **command.model_dump(exclude={"project_id", "shot_id", "experiment_branch_id"}),
                    plan_fingerprint=plan.plan_fingerprint,
                    accepted_approximations=plan.accepted_approximations,
                ),
            )
            await session.commit()
            event = await session.scalar(
                select(OutboxEvent).where(OutboxEvent.topic == "production.facts.v1")
            )
            assert event is not None
            event_id = event.event_id

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
                event_id=event_id,
            )
            await session.commit()

        original = director_wakeup._enqueue_runtime_event

        async def injected_failure(*args, **kwargs):
            raise RuntimeError("Injected director failure before wakeup completion")

        monkeypatch.setattr(director_wakeup, "_enqueue_runtime_event", injected_failure)
        assert not await director_wakeup.process_director_wakeup(factory, inbox_id=inbox_id)

        async with admin() as session:
            run = await session.get(NodeRun, receipt.node_run_id)
            failed = await session.get(DirectorWakeup, inbox_id)
            assert run is not None and run.status == "queued"
            assert failed is not None
            assert failed.completed_at is None and failed.attempt_count == 1
            assert failed.last_error == "RuntimeError"
            assert failed.next_attempt_at > datetime.now(UTC)
            assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 0

        if delivery == "dead_letter":
            for attempt in range(2, 6):
                async with admin() as session:
                    pending = await session.get(DirectorWakeup, inbox_id)
                    assert pending is not None
                    pending.next_attempt_at = datetime.now(UTC)
                    await session.commit()
                assert not await director_wakeup.process_director_wakeup(
                    factory, inbox_id=inbox_id
                )
                async with admin() as session:
                    pending = await session.get(DirectorWakeup, inbox_id)
                    assert pending is not None and pending.attempt_count == attempt
            async with admin() as session:
                pending = await session.get(DirectorWakeup, inbox_id)
                assert pending is not None
                assert pending.dead_letter_at is not None and pending.completed_at is None
                failed_at = pending.dead_letter_at
                assert await replay_failed_wakeup(
                    session,
                    actor=actor,
                    project_id=project.id,
                    inbox_id=inbox_id,
                    expected_dead_letter_at=failed_at,
                )
                await session.commit()
            monkeypatch.setattr(director_wakeup, "_enqueue_runtime_event", original)
            assert await director_wakeup.process_director_wakeup(factory, inbox_id=inbox_id)
            return

        async with admin() as session:
            pending = await session.get(DirectorWakeup, inbox_id)
            assert pending is not None
            pending.next_attempt_at = datetime.now(UTC)
            await session.commit()
        monkeypatch.setattr(director_wakeup, "_enqueue_runtime_event", original)

        if delivery == "direct":
            results = await asyncio.gather(
                director_wakeup.process_director_wakeup(factory, inbox_id=inbox_id),
                director_wakeup.process_director_wakeup(factory, inbox_id=inbox_id),
            )
            assert sorted(results) == [False, True]
        else:
            child_source = """
import asyncio, os
from uuid import UUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.shared.model_registry import load_all_models
import app.director.wakeup as wakeup_module
load_all_models()
async def paused(*args, **kwargs):
    print("checkpoint-ready", flush=True)
    await asyncio.Event().wait()
wakeup_module._enqueue_runtime_event = paused
async def main():
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await wakeup_module.process_director_wakeup(
        factory,
        inbox_id=UUID(os.environ["TEST_WAKEUP_ID"]),
    )
asyncio.run(main())
"""
            child = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                child_source,
                env={
                    **os.environ,
                    "DATABASE_URL": _async_url(dbname),
                    "TEST_WAKEUP_ID": str(inbox_id),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
            assert await director_wakeup.process_director_wakeup(factory, inbox_id=inbox_id)

        async with admin() as session:
            done = await session.get(DirectorWakeup, inbox_id)
            assert done is not None and done.completed_at is not None
            assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 0
            run = await session.get(NodeRun, receipt.node_run_id)
            assert run is not None and run.status == "queued"
    finally:
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)
