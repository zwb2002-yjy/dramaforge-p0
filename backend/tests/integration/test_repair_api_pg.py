"""Repair API command receipts under PostgreSQL RLS, without provider calls."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.api.v1.workbench import (
    RepairCloseBody,
    RepairCreateBody,
    RepairStepExecuteBody,
    close_repair,
    create_repair,
    execute_repair_step,
    preview_repair_step,
    read_repair,
)
from app.execution.models import NodeRun
from app.production.models import RepairRequest, RepairStep
from app.production.repair_service import RepairService
from app.shared.db import set_rls_context
from app.shared.errors import AppError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_repair_staged import _seed, _seed_model_infra


@pytest.mark.asyncio
async def test_repair_receipts_survive_api_commit_and_concurrent_retries():
    dbname = f"dramaforge_repair_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin = create_async_engine(_async_url(dbname))
    app = create_async_engine(
        _async_url(dbname),
        connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        admin_factory = async_sessionmaker(admin, expire_on_commit=False)
        factory = async_sessionmaker(app, expire_on_commit=False)
        async with admin_factory() as session:
            project, shot, user = await _seed(session)
            _, _, stranger = await _seed(session)
            await _seed_model_infra(session, project=project, user=user)
            plan = await RepairService(session).build_repair_plan(project=project, shot_id=shot.id)
            await session.commit()

        async def scope(session):
            await set_rls_context(
                session, user_id=user.id, workspace_id=project.workspace_id, project_id=project.id
            )

        body = RepairCreateBody(
            repair_option="regenerate_keyframe_then_video",
            plan_hash=plan.plan_hash,
            idempotency_key="pg-repair",
        )

        async def create():
            async with factory() as session:
                await scope(session)
                result = await create_repair(project.id, shot.id, body, user, session, None)
                # Route has committed; transaction-local RLS is gone. The response
                # had to be built before commit, not re-read from the empty scope.
                assert await session.scalar(select(RepairRequest.id)) is None
                return result

        first, repeated = await asyncio.gather(create(), create())
        assert first.id == repeated.id
        assert first.next_action == "execute_step"
        async with factory() as session:
            await scope(session)
            preview = await preview_repair_step(project.id, shot.id, first.id, user, session)
        command = RepairStepExecuteBody(
            expected_plan_fingerprint=preview.plan.plan_fingerprint,
            expected_step_ordinal=1,
            idempotency_key="pg-step",
        )

        async def execute():
            async with factory() as session:
                await scope(session)
                return await execute_repair_step(
                    project.id,
                    shot.id,
                    first.id,
                    command,
                    user,
                    session,
                    None,
                )

        run, duplicate = await asyncio.gather(execute(), execute())
        assert run.node_run_id == duplicate.node_run_id
        assert run.next_action == "wait"
        async with admin_factory() as session:
            assert await session.scalar(select(func.count()).select_from(RepairRequest)) == 1
            assert await session.scalar(select(func.count()).select_from(RepairStep)) == 1
            persisted = await session.get(NodeRun, run.node_run_id)
            assert persisted is not None and persisted.status == "queued"

        async with factory() as session:
            await set_rls_context(session, user_id=stranger.id)
            with pytest.raises(AppError):
                await read_repair(project.id, shot.id, first.id, stranger, session)
        async with factory() as session:
            await scope(session)
            with pytest.raises(AppError) as active:
                await close_repair(
                    project.id,
                    shot.id,
                    first.id,
                    RepairCloseBody(reason="abandoned"),
                    user,
                    session,
                    None,
                )
            assert active.value.details["code"] == "REPAIR_RUN_ACTIVE"
    finally:
        await app.dispose()
        await admin.dispose()
        await _drop_database(dbname)
