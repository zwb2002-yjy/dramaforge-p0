"""Concurrent first writes and revision allocation use a stable parent lock."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from app.access.models import Project, User
from app.api.v1.director_board import DirectorBoardBody, save_director_board
from app.config import get_settings
from app.execution.models import GraphNode
from app.production.models import DirectorBoardState
from app.production.workbench_execution import ensure_stage_review_run
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import ProviderConnection
from app.providers.openai_compatible_media import OPENAI_IMAGES_PROFILE
from app.providers.workspace_credentials import configured_byok_keyring
from app.security.credentials import store_credential
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark
from tests.unit.test_review_gate import _artifact, _env, _review_run


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,existing", [
    ("board", False), ("credential", False), ("credential", True),
    ("connection", False), ("connection", True), ("review", False), ("review", True),
])
async def test_concurrent_allocations_serialize_on_parent_pg(pg_session, kind, existing):
    user, project, shot = await _env(pg_session)
    connection = ProviderConnection(
        workspace_id=project.workspace_id, provider_type="openai_compatible_media",
        display_name="Synthetic", base_url="https://example.invalid",
        protocol_profile=OPENAI_IMAGES_PROFILE, auth_mode="none",
        created_by=user.id, updated_by=user.id,
    )
    pg_session.add(connection)
    artifact = await _artifact(pg_session, project_id=project.id)
    producer = await _review_run(pg_session, project_id=project.id, shot_id=shot.id,
                                created_by=user.id, node_key="keyframe", status="completed",
                                review_artifact_id=artifact.id)
    artifact.produced_by_run_id = producer.id
    producer.result_artifact_id = artifact.id
    producer.status = "completed"
    pg_session.add(GraphNode(graph_version_id=producer.graph_version_id,
                             node_key="identity_review", node_type="identity_review",
                             display_name="Review", cacheable=False))
    await pg_session.flush()
    ids = dict(user=user.id, project=project.id, shot=shot.id, workspace=project.workspace_id,
               connection=connection.id, artifact=artifact.id)
    keyring = configured_byok_keyring(get_settings())

    async def allocate(session):
        if kind == "credential":
            row = await store_credential(session, workspace_id=ids["workspace"],
                provider="concurrency", plaintext="synthetic", keyring=keyring)
            return row.id, row.revision_no
        if kind == "connection":
            row = await ProviderConnectionService(session).create_connection_revision(
                connection=await session.get(ProviderConnection, ids["connection"]))
            return row.id, row.revision_no
        if kind == "review":
            row = await ensure_stage_review_run(session,
                project=await session.get(Project, ids["project"]), shot=shot,
                artifact_id=ids["artifact"], stage="image_keyframe", created_by=ids["user"],
                force=existing)
            return row.id, row.attempt_no
        row = await save_director_board(project_id=ids["project"], shot_id=ids["shot"],
            body=DirectorBoardBody(mode="2d", camera={"x": 1}),
            user=await session.get(User, ids["user"]), session=session, _csrf=None)
        return row.id, row.version

    if existing:
        await allocate(pg_session)
    await pg_session.commit()
    factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
    written, release, second_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    async def create(name):
        async with factory() as session:
            pids[name] = await session.scalar(text("SELECT pg_backend_pid()"))
            if name == "second":
                second_ready.set()
            original_commit = session.commit

            async def commit():
                await session.flush()
                if name == "first":
                    written.set()
                    await release.wait()
                await original_commit()

            session.commit = AsyncMock(side_effect=commit)
            result = await allocate(session)
            if kind != "board":
                await session.commit()
            return result

    first = asyncio.create_task(create("first"))
    second = None
    try:
        await asyncio.wait_for(written.wait(), timeout=10)
        second = asyncio.create_task(create("second"))
        await asyncio.wait_for(second_ready.wait(), timeout=10)

        async def wait_for_lock():
            while pids["first"] not in await pg_session.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["second"]}
            ):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_lock(), timeout=10)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
    if kind == "review" and not existing:
        assert results[0] == results[1]
    else:
        assert [result[1] for result in results] == ([2, 3] if existing else [1, 2])
    if kind == "board":
        pg_session.expire_all()
        board = await pg_session.scalar(select(DirectorBoardState).where(
            DirectorBoardState.shot_id == ids["shot"]))
        assert board.version == 2
