"""Migration-head proof of source scope, concurrent admission and original history."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.project_files import ProjectFileService
from app.events.models import OutboxEvent
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_concurrent_source_admission_and_rls_at_migration_head():
    dbname = f"dramaforge_sources_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = InMemoryObjectStore()
    try:
        _alembic(dbname)
        async with factory() as session:
            actor = User(email=f"sources-{uuid4()}@example.com", display_name="Owner",
                         password_hash="x")
            session.add(actor)
            await session.flush()
            workspace = Workspace(name="Sources", owner_user_id=actor.id)
            session.add(workspace)
            await session.flush()
            projects = [Project(workspace_id=workspace.id, name=name, aspect_ratio="16:9",
                                budget_limit=0) for name in ("First", "Second")]
            session.add_all(projects)
            await session.commit()
            actor_id, workspace_id = actor.id, workspace.id
            project_id, other_project = [project.id for project in projects]

        async def admit(key, *, file_id=None, expected_version=None, data=b"Local original"):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(session, user_id=actor_id, workspace_id=workspace_id,
                                      project_id=project_id)
                session.info["selected_workspace_id"] = workspace_id
                owner = await session.get(User, actor_id)
                assert owner is not None
                service = ProjectFileService(
                    session, store=store, actor=owner, project_id=project_id,
                )
                try:
                    row = await service.upload(filename="history.txt", data=data,
                                               mime_type="text/plain", request_key=key,
                                               file_id=file_id, expected_version=expected_version)
                    await session.commit()
                    return row.id
                except ConflictError:
                    await session.rollback()
                    return None

        first, replay = await asyncio.gather(admit("same"), admit("same"))
        assert first is not None and first == replay
        async with factory() as session:
            revision = await session.get(ProjectFileRevision, first)
            assert revision is not None
            file_id = revision.file_id
            original_key = revision.object_key
            assert await session.scalar(select(func.count(ProjectFile.id))) == 1
            assert await session.scalar(select(func.count(OutboxEvent.id))) == 1
            forged = {column.name: getattr(revision, column.name)
                      for column in ProjectFileRevision.__table__.columns}
            forged.update(id=uuid4(), project_id=other_project, number=77)
            with pytest.raises(IntegrityError, match="fk_project_file_revision_scope"):
                async with session.begin_nested():
                    await session.execute(insert(ProjectFileRevision).values(**forged))
        updates = await asyncio.gather(
            admit("update-a", file_id=file_id, expected_version=1),
            admit("update-b", file_id=file_id, expected_version=1),
        )
        assert sum(value is not None for value in updates) == 1
        invalid_id = await admit("invalid", file_id=file_id, expected_version=2, data=b"\xff")
        async with factory() as session:
            session.info["selected_workspace_id"] = workspace_id
            owner = await session.get(User, actor_id)
            assert owner is not None
            service = ProjectFileService(session, store=store, actor=owner, project_id=project_id)
            assert (await service.extract(invalid_id)).status == "failed"
            await session.commit()

        async def retry():
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(session, user_id=actor_id, workspace_id=workspace_id,
                                      project_id=project_id)
                session.info["selected_workspace_id"] = workspace_id
                owner = await session.get(User, actor_id)
                assert owner is not None
                service = ProjectFileService(
                    session, store=store, actor=owner, project_id=project_id,
                )
                try:
                    await service.retry_extraction(invalid_id, request_key="retry-failed")
                    await session.commit()
                except ConflictError:
                    await session.rollback()  # Update won; the old revision cannot be retried.

        await asyncio.wait_for(asyncio.gather(
            admit("update-during-retry", file_id=file_id, expected_version=3), retry(),
        ), timeout=10)
        async with factory() as session:
            assert await session.scalar(select(func.count(ProjectFileRevision.id))) == 4
            assert await session.scalar(select(func.count(OutboxEvent.id))) in {4, 5}
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(session, user_id=actor_id, workspace_id=workspace_id,
                                  project_id=other_project)
            assert list(await session.scalars(select(ProjectFile))) == []
            assert list(await session.scalars(select(ProjectFileRevision))) == []
            await set_rls_context(session, user_id=actor_id, workspace_id=workspace_id,
                                  project_id=project_id)
            with pytest.raises(DBAPIError, match="row-level security"):
                async with session.begin_nested():
                    await session.execute(insert(ProjectFile).values(
                        id=uuid4(), project_id=other_project, filename="forbidden.txt",
                        content_version=1, version=1,
                    ))
            owner = await session.get(User, actor_id)
            assert owner is not None
            session.info["selected_workspace_id"] = workspace_id
            service = ProjectFileService(session, store=store, actor=owner, project_id=project_id)
            await service.unlink(file_id, expected_version=4)
            await session.commit()
        assert await store.get_bytes(object_key=original_key) == b"Local original"
        environment = {**os.environ, "DATABASE_URL": _async_url(dbname)}

        def migration(*arguments):
            return subprocess.run(
                [sys.executable, "-m", "alembic", *arguments],
                cwd=Path(__file__).resolve().parents[2], env=environment,
                capture_output=True, text=True, check=False,
            )

        blocked = migration("downgrade", "20261111_0097")
        assert blocked.returncode != 0
        assert "PROJECT_FILES_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE" in blocked.stderr
        async with factory() as session:
            assert await session.scalar(select(func.count(ProjectFileRevision.id))) == 4
            # Only this test-owned database: exercise an empty-source rollback.
            await session.execute(delete(ProjectFileRevision))
            await session.execute(delete(ProjectFile))
            await session.commit()
        downgraded = migration("downgrade", "20261111_0097")
        assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
        _alembic(dbname)
        checked = migration("check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
    finally:
        await engine.dispose()
        await _drop_database(dbname)
