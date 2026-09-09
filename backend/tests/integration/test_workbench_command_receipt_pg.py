"""R4c2 real PostgreSQL command/attempt serialization and mode-lock proof."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.access.models import Project, ProjectCreativeProfile, User
from app.assets.models import Shot
from app.director.business_checkpoints import DirectorBusinessCheckpoints
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.execution.models import NodeRun, ProviderOperation
from app.production.workbench_execution import WorkbenchExecutionService
from app.providers.models import ProviderModelBinding
from app.shared.db import set_rls_context
from app.shared.errors import ValidationAppError
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import (
    pytestmark as pytestmark,
)
from tests.unit.test_workbench_execution import _input, _seed, _seed_video_shot


@pytest.mark.asyncio
async def test_postgres_command_receipts_attempts_and_proactive_mode_lock(monkeypatch):
    dbname = f"dramaforge_command_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            project, binding, actor = await _seed(session)
            shot, _artifact = await _seed_video_shot(session, project=project, user=actor)
            session.add(ProjectCreativeProfile(project_id=project.id, start_type="FREE",
                                               director_autonomy="AUTO"))
            await session.commit()
            command = _input(project_id=project.id, shot_id=shot.id,
                             requested_binding_id=binding.id, expected_shot_version=shot.version)
            plan = await WorkbenchExecutionService(session, user_id=actor.id).build_plan(
                project=project, execution_input=command,
            )
            ids = (project.id, project.workspace_id, actor.id, shot.id, binding.id)
        project_id, workspace_id, actor_id, shot_id, binding_id = ids
        original_lock = WorkbenchExecutionService.lock_command_scope
        arrivals = 0
        ready = asyncio.Event()

        async def racing_lock(self, *, project_id):
            nonlocal arrivals
            arrivals += 1
            if arrivals == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 10)
            await original_lock(self, project_id=project_id)

        monkeypatch.setattr(WorkbenchExecutionService, "lock_command_scope", racing_lock)

        async def dispatch(key):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(session, user_id=actor_id, workspace_id=workspace_id,
                                      project_id=project_id)
                project = await session.get(Project, project_id)
                actor = await session.get(User, actor_id)
                service = WorkbenchExecutionService(session, user_id=actor_id)
                run = await service.create_and_dispatch(
                    project=project, execution_input=command, prepared_plan=plan,
                    idempotency_key_override=key,
                )
                turn = await DirectorBusinessCheckpoints(session).track_execution(
                    project=project, actor=actor, run=run,
                )
                await session.commit()
                return run.id, run.attempt_no, turn.id

        duplicate = await asyncio.gather(dispatch("same-command"), dispatch("same-command"))
        assert duplicate[0] == duplicate[1]
        monkeypatch.setattr(WorkbenchExecutionService, "lock_command_scope", original_lock)
        distinct = await asyncio.gather(dispatch("new-command-a"), dispatch("new-command-b"))
        assert sorted(item[1] for item in distinct) == [2, 3]
        async with factory() as session:
            await set_rls_context(session, user_id=actor_id, workspace_id=workspace_id,
                                  project_id=project_id)
            assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 3
            assert await session.scalar(select(func.count()).select_from(ProviderOperation)) == 0
            runs = list((await session.execute(select(NodeRun).where(
                NodeRun.idempotency_key.like("workbench:video:%")
            ).order_by(NodeRun.attempt_no))).scalars())
            assert len(runs) == 3
            assert runs[1].parent_run_id == runs[0].id and runs[2].parent_run_id == runs[1].id
            await session.execute(update(ProviderModelBinding).where(
                ProviderModelBinding.id == binding_id).values(enabled=False))
            await session.execute(update(Shot).where(Shot.id == shot_id).values(version=10))
            await session.commit()
        # Exact replay ignores newer mutable state; it is not a new dispatch.
        assert await dispatch("same-command") == duplicate[0]

        async with factory() as updater:
            await updater.execute(select(ProjectCreativeProfile).where(
                ProjectCreativeProfile.project_id == project_id).with_for_update())
            await updater.execute(update(ProjectCreativeProfile).where(
                ProjectCreativeProfile.project_id == project_id).values(director_autonomy="MANUAL"))
            started = asyncio.Event()
            checking_pid = None

            async def check_authorization():
                nonlocal checking_pid
                async with factory() as session:
                    checking_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                    started.set()
                    with pytest.raises(ValidationAppError) as disabled:
                        await DirectorTurnService(session).require_proactive_authorization(
                            project_id=project_id,
                        )
                    assert disabled.value.details["code"] == "DIRECTOR_PROACTIVE_DISABLED"

            checker = asyncio.create_task(check_authorization())
            await asyncio.wait_for(started.wait(), 10)
            # Verify an actual PostgreSQL lock wait rather than guessing from a sleep.
            async with factory() as observer:
                for _ in range(200):
                    blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"),
                                                     {"pid": checking_pid})
                    if blockers:
                        break
                    await asyncio.sleep(0.01)
                assert blockers, "proactive guard did not wait on the mode transaction"
            await updater.commit()
            await asyncio.wait_for(checker, 10)
    finally:
        await engine.dispose()
        await _drop_database(dbname)
