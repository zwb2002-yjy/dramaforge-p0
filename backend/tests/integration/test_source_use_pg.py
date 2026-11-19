"""Source-use RLS, append-only declarations and refused populated downgrade (PG)."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.source_use import SourceUseService
from app.assets.source_use_models import ArtifactSourceUse, SourceUseRevision, SourceUseSubject
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from pg_support import alembic_head
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

BACKEND = Path(__file__).resolve().parents[2]


def migration(name, direction, target=None):
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, *([target] if target is not None else [])],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": _async_url(name)},
        capture_output=True,
        text=True,
        check=False,
    )


@asynccontextmanager
async def source_use_database():
    name = f"dramaforge_sourceuse_{uuid4().hex[:10]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        _alembic(name)
        yield name, engine, factory
    finally:
        await engine.dispose()
        await _drop_database(name)


async def test_declarations_are_project_scoped_append_only_and_versioned():
    async with source_use_database() as (name, engine, factory):
        async with factory() as session:
            owner = User(email=f"{uuid4()}@example.com", display_name="O", password_hash="x")
            other = User(email=f"{uuid4()}@example.com", display_name="X", password_hash="x")
            session.add_all([owner, other])
            await session.flush()
            workspace = Workspace(name="机构", owner_user_id=owner.id)
            foreign_workspace = Workspace(name="其它", owner_user_id=other.id)
            session.add_all([workspace, foreign_workspace])
            await session.flush()
            first = Project(
                workspace_id=workspace.id, name="甲", aspect_ratio="16:9", budget_limit=0,
                work_type="single_comic",
            )
            second = Project(
                workspace_id=workspace.id, name="乙", aspect_ratio="16:9", budget_limit=0,
                work_type="single_comic",
            )
            session.add_all([first, second])
            await session.commit()
            ids = {
                "owner": owner.id, "workspace": workspace.id, "first": first.id,
                "second": second.id,
            }
            session.info["selected_workspace_id"] = workspace.id
            file_revision = uuid4()
            declared = await SourceUseService(
                session, actor=owner, project=first,
            ).declare(
                file_revision_id=file_revision, allowed_uses=["research"],
                statement="本人整理，可用于研究引用。", request_key="declare",
            )
            await session.commit()
            declared_id = declared.id
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["owner"], workspace_id=ids["workspace"],
                project_id=ids["second"],
            )
            assert await session.scalar(select(func.count(SourceUseSubject.id))) == 0
            assert await session.scalar(select(func.count(SourceUseRevision.id))) == 0
            await session.rollback()
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["owner"], workspace_id=ids["workspace"],
                project_id=ids["first"],
            )
            assert await session.scalar(select(func.count(SourceUseRevision.id))) == 1
            # Revisions are append-only; the subject pointer may advance.
            for statement in (
                "UPDATE source_use_revisions SET state = 'declared'",
                "DELETE FROM source_use_revisions",
                "DELETE FROM source_use_subjects",
            ):
                with pytest.raises(ProgrammingError):
                    async with session.begin_nested():
                        await session.execute(text(statement))
            await session.rollback()
        async with factory() as session:
            session.info["selected_workspace_id"] = ids["workspace"]
            owner = await session.get(User, ids["owner"])
            project = await session.get(Project, ids["first"])
            service = SourceUseService(session, actor=owner, project=project)
            revoked = await service.declare(
                file_revision_id=file_revision, allowed_uses=[], statement="撤回",
                request_key="revoke", state="revoked",
            )
            await session.commit()
            assert revoked.number == 2 and revoked.state == "revoked"
            subject = await session.scalar(select(SourceUseSubject))
            assert subject is not None and subject.version == 3
            assert subject.current_revision_id == revoked.id
            with pytest.raises(ConflictError):
                await service.declare(
                    file_revision_id=file_revision, allowed_uses=["research"],
                    statement="恢复", request_key="restore",
                )
            assert declared_id != revoked.id


async def test_artifact_provenance_keeps_original_declaration_identity():
    async with source_use_database() as (name, engine, factory), factory() as session:
        owner = User(email=f"{uuid4()}@example.com", display_name="O", password_hash="x")
        session.add(owner)
        await session.flush()
        workspace = Workspace(name="机构", owner_user_id=owner.id)
        session.add(workspace)
        await session.flush()
        project = Project(
            workspace_id=workspace.id, name="甲", aspect_ratio="16:9", budget_limit=0,
            work_type="single_comic",
        )
        session.add(project)
        await session.commit()
        session.info["selected_workspace_id"] = workspace.id
        service = SourceUseService(session, actor=owner, project=project)
        file_revision = uuid4()
        declared = await service.declare(
            file_revision_id=file_revision, allowed_uses=["creation"],
            statement="可用于画面参考。", request_key="declare",
        )
        subject = await session.scalar(select(SourceUseSubject))
        assert subject is not None
        provenance = await service.record_artifact_source_use(
            artifact_id=uuid4(),
            source_subject_id=subject.id,
            source_project_id=project.id,
            source_revision_id=declared.id,
            consumer_node_run_id=uuid4(),
            input_role="reference_image",
        )
        await session.commit()
        assert provenance.source_revision_id == declared.id
        # The declaration used by the artifact stays readable after revocation.
        await service.declare(
            file_revision_id=file_revision, allowed_uses=[], statement="撤回",
            request_key="revoke", state="revoked",
        )
        await session.commit()
        assert await session.scalar(
            select(func.count(ArtifactSourceUse.id))
        ) == 1
        assert (
            await session.scalar(
                select(ArtifactSourceUse.source_revision_id)
            )
        ) == declared.id


async def test_populated_source_use_blocks_downgrade():
    name = f"dramaforge_sourceuse_mig_{uuid4().hex[:8]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        assert migration(name, "upgrade", "head").returncode == 0
        async with factory() as session:
            owner = User(email=f"{uuid4()}@example.com", display_name="O", password_hash="x")
            session.add(owner)
            await session.flush()
            workspace = Workspace(name="机构", owner_user_id=owner.id)
            session.add(workspace)
            await session.flush()
            project = Project(
                workspace_id=workspace.id, name="甲", aspect_ratio="16:9", budget_limit=0,
                work_type="single_comic",
            )
            session.add(project)
            await session.flush()
            session.info["selected_workspace_id"] = workspace.id
            await SourceUseService(session, actor=owner, project=project).declare(
                file_revision_id=uuid4(), allowed_uses=["research"],
                statement="声明", request_key="declare",
            )
            await session.commit()
        refused = migration(name, "downgrade", "20261117_0103")
        assert refused.returncode != 0
        assert "SOURCE_USE_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE" in refused.stderr
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == alembic_head()
        checked = migration(name, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
    finally:
        await engine.dispose()
        await _drop_database(name)
