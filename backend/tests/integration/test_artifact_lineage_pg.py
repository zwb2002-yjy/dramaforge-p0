"""PostgreSQL concurrency coverage for canonical Artifact identity."""

from __future__ import annotations

import asyncio
import hashlib
from uuid import uuid4

import pytest
from app.execution.artifact_lineage import get_or_create_artifact
from app.execution.models import Artifact
from app.shared.db import set_rls_context
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import _project
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark


@pytest.mark.asyncio
async def test_concurrent_identical_artifact_insert_reuses_single_winner(pg_session):
    user, project_id, workspace_id = await _project(pg_session)
    factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
    content_hash = hashlib.sha256(f"same-audio-{uuid4()}".encode()).hexdigest()
    start = asyncio.Event()

    async def create(index: int):
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=user.id,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            await start.wait()
            artifact = await get_or_create_artifact(
                session,
                project_id=project_id,
                artifact_type="audio",
                object_key=f"projects/{project_id}/race/{index}.wav",
                content_hash=content_hash,
                mime_type="audio/wav",
                byte_size=128,
                produced_by_run_id=None,
                allow_cross_run_reuse=True,
            )
            await session.commit()
            return artifact.id

    tasks = [asyncio.create_task(create(index)) for index in range(12)]
    await asyncio.sleep(0)
    start.set()
    artifact_ids = await asyncio.gather(*tasks)

    await set_rls_context(
        pg_session,
        user_id=user.id,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    count = await pg_session.scalar(
        select(func.count(Artifact.id)).where(
            Artifact.project_id == project_id,
            Artifact.content_hash == content_hash,
            Artifact.artifact_type == "audio",
        )
    )
    assert len(set(artifact_ids)) == 1
    assert count == 1
