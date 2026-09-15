"""Database proof of duplicate intake and atomic durable wakeup intent."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.contracts.domain_events import ExecutionAccepted
from app.director.inbox import receive_production_event
from app.director.inbox_models import DirectorInbox, DirectorWakeup
from app.production.application.events import append_production_notice
from app.shared.db import set_rls_context
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _seed


@pytest.mark.asyncio
async def test_inbox_duplicates_and_interrupted_intake_keep_one_durable_wakeup():
    dbname = f"dramaforge_d2_inbox_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            project, _binding, actor = await _seed(session)
            event_id = await append_production_notice(
                session, project_id=project.id, actor_id=actor.id,
                notice=ExecutionAccepted(shot_id=uuid4(), node_run_id=uuid4()),
            )
            await session.commit()
            project_id, workspace_id, actor_id = project.id, project.workspace_id, actor.id

        async def intake(*, commit=True):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(session, user_id=actor_id, workspace_id=workspace_id,
                                      project_id=project_id)
                inbox_id = await receive_production_event(
                    session, project_id=project_id, event_id=event_id,
                )
                if commit:
                    await session.commit()
                else:
                    await session.rollback()
                return inbox_id

        await intake(commit=False)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(DirectorInbox)) == 0
            assert await session.scalar(select(func.count()).select_from(DirectorWakeup)) == 0
        ids = await asyncio.gather(intake(), intake())
        assert ids[0] == ids[1]
        # New process/session can recover this pending row without any queue
        # having received the signal. Queue delivery itself is tested separately.
        async with factory() as session:
            pending = (await session.scalars(select(DirectorWakeup))).all()
            assert len(pending) == 1 and pending[0].completed_at is None
            pending[0].completed_at = datetime.now(UTC)
            await session.commit()
        assert await intake() == ids[0]
        async with factory() as session:
            pending = (await session.scalars(select(DirectorWakeup))).all()
            assert len(pending) == 1 and pending[0].completed_at is not None
    finally:
        await engine.dispose()
        await _drop_database(dbname)
