"""Immutable extraction snapshots: legacy conversion, RLS scope and append-only grants."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError
from app.storage.minio_store import InMemoryObjectStore
from pg_support import alembic_head
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
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
async def source_database():
    name = f"dramaforge_sources_{uuid4().hex[:10]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        _alembic(name)
        yield name, engine, factory
    finally:
        await engine.dispose()
        await _drop_database(name)


async def test_legacy_excerpts_convert_to_zero_based_fragments_and_block_downgrade():
    name = f"dramaforge_source_legacy_{uuid4().hex[:8]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    try:
        # Seed one real parsed revision with the historical one-based shape.
        result = migration(name, "upgrade", "20261117_0100")
        assert result.returncode == 0, result.stderr
        user_id, workspace_id, project_id, file_id, revision_id = (
            uuid4(), uuid4(), uuid4(), uuid4(), uuid4(),
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users(id,email,display_name,password_hash) "
                    "VALUES (:id,:email,'Owner','x')"
                ),
                {"id": user_id, "email": f"{uuid4()}@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO workspaces(id,owner_user_id,name) "
                    "VALUES (:id,:owner,'机构')"
                ),
                {"id": workspace_id, "owner": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects(id,workspace_id,name,aspect_ratio,budget_limit) "
                    "VALUES (:id,:workspace,'Legacy source','16:9',0)"
                ),
                {"id": project_id, "workspace": workspace_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO project_files(id,project_id,filename,content_version,version) "
                    "VALUES (:id,:project,'地方志.txt',1,1)"
                ),
                {"id": file_id, "project": project_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO project_file_revisions(id,project_id,file_id,number,filename,"
                    "object_key,content_hash,byte_size,mime_type,request_key,request_hash,"
                    "status,attempt,parser_version,excerpts) VALUES "
                    "(:id,:project,:file,1,'地方志.txt','k','" + "a" * 64 + "',10,"
                    "'text/plain','legacy','" + "b" * 64 + "','parsed',1,'native-text-v1',"
                    ':excerpts)'
                ),
                {
                    "id": revision_id,
                    "project": project_id,
                    "file": file_id,
                    "excerpts": '[{"text":"古桥","location":{"line":1}},'
                                '{"text":"待考","location":{"line":3}}]',
                },
            )
        upgraded = migration(name, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        async with engine.connect() as connection:
            extraction = (
                await connection.execute(
                    text(
                        "SELECT id, parser_key, attempt, extraction_schema_version, coverage, "
                        "processor_evidence, content_hash FROM source_extractions"
                    )
                )
            ).one()
            assert extraction.parser_key == "legacy-native-text-v1"
            assert extraction.attempt == 1 and extraction.extraction_schema_version == 2
            assert extraction.coverage["complete"] is True
            assert extraction.processor_evidence["coordinate_system"]["index_base"] == 0
            assert len(extraction.content_hash) == 64
            fragments = (
                await connection.execute(
                    text(
                        "SELECT ordinal, locator_kind, locator, text_content, evidence_meta "
                        "FROM source_fragments ORDER BY ordinal"
                    )
                )
            ).all()
            assert [row.ordinal for row in fragments] == [0, 1]
            assert [row.text_content for row in fragments] == ["古桥", "待考"]
            assert fragments[0].locator == {
                "kind": "paragraph", "container_key": "text-lines", "paragraph_start": 0,
                "paragraph_end": 1, "char_start": 0, "char_end": 2,
            }
            assert fragments[1].locator["paragraph_start"] == 2
            assert fragments[1].evidence_meta["original_location"] == {"line": 3}
            assert (
                await connection.execute(
                    text("SELECT current_extraction_id FROM project_file_revisions")
                )
            ).scalar_one() == extraction.id
        refused = migration(name, "downgrade", "20261117_0100")
        assert refused.returncode != 0
        assert "SOURCE_EXTRACTIONS_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE" in refused.stderr
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == alembic_head()
    finally:
        await engine.dispose()
        await _drop_database(name)


async def test_unsupported_legacy_location_blocks_conversion_with_safe_ids():
    name = f"dramaforge_source_blocked_{uuid4().hex[:8]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    try:
        assert migration(name, "upgrade", "20261117_0100").returncode == 0
        user_id, workspace_id, project_id, file_id, revision_id = (
            uuid4(), uuid4(), uuid4(), uuid4(), uuid4(),
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users(id,email,display_name,password_hash) "
                    "VALUES (:id,:email,'Owner','x')"
                ),
                {"id": user_id, "email": f"{uuid4()}@example.com"},
            )
            await connection.execute(
                text("INSERT INTO workspaces(id,owner_user_id,name) VALUES (:id,:owner,'机构')"),
                {"id": workspace_id, "owner": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects(id,workspace_id,name,aspect_ratio,budget_limit) "
                    "VALUES (:id,:workspace,'Blocked','16:9',0)"
                ),
                {"id": project_id, "workspace": workspace_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO project_files(id,project_id,filename,content_version,version) "
                    "VALUES (:id,:project,'扫描件.txt',1,1)"
                ),
                {"id": file_id, "project": project_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO project_file_revisions(id,project_id,file_id,number,filename,"
                    "object_key,content_hash,byte_size,mime_type,request_key,request_hash,"
                    "status,attempt,parser_version,excerpts) VALUES "
                    "(:id,:project,:file,1,'扫描件.txt','k','" + "a" * 64 + "',10,"
                    "'text/plain','blocked','" + "b" * 64 + "','parsed',1,'native-text-v1',"
                    ':excerpts)'
                ),
                {
                    "id": revision_id,
                    "project": project_id,
                    "file": file_id,
                    "excerpts": '[{"text":"未知","location":{"page":4}}]',
                },
            )
        blocked = migration(name, "upgrade", "head")
        assert blocked.returncode != 0
        assert "SOURCE_LEGACY_LOCATION_UNSUPPORTED" in blocked.stderr
        assert str(revision_id) in blocked.stderr
        async with engine.connect() as connection:
            # Fail-closed: the transaction rolled back, the legacy row is intact
            # and the new evidence tables were never created.
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == "20261117_0100"
            assert (
                await connection.execute(
                    text("SELECT to_regclass('public.source_extractions')")
                )
            ).scalar_one() is None
            assert (
                await connection.execute(
                    text("SELECT excerpts FROM project_file_revisions WHERE id=:id"),
                    {"id": revision_id},
                )
            ).scalar_one() == [{"text": "未知", "location": {"page": 4}}]
    finally:
        await engine.dispose()
        await _drop_database(name)


async def test_app_role_reads_only_its_project_and_cannot_rewrite_snapshots():
    async with source_database() as (name, engine, factory):
        async with factory() as session:
            owner = User(email=f"{uuid4()}@example.com", display_name="Owner", password_hash="x")
            other = User(email=f"{uuid4()}@example.com", display_name="Other", password_hash="x")
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
            ids = (owner.id, workspace.id, first.id, second.id)
            store = InMemoryObjectStore()
            extractions = []
            for project_id, body in ((first.id, b"alpha\n\nbeta"), (second.id, b"other project")):
                await set_rls_context(
                    session, user_id=owner.id, workspace_id=workspace.id, project_id=project_id,
                )
                session.info["selected_workspace_id"] = workspace.id
                actor = await session.get(User, owner.id)
                service = ProjectFileService(
                    session, store=store, actor=actor, project_id=project_id,
                )
                revision = await service.upload(
                    filename="source.txt", data=body, mime_type="text/plain",
                    request_key=f"upload-{project_id}",
                )
                await service.extract(revision.id)
                extractions.append((project_id, revision.current_extraction_id))
            await session.commit()
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids[0], workspace_id=ids[1], project_id=ids[2],
            )
            session.info["selected_workspace_id"] = ids[1]
            actor = await session.get(User, ids[0])
            service = ProjectFileService(
                session, store=InMemoryObjectStore(), actor=actor, project_id=ids[2],
            )
            visible = await service.read_extraction(extractions[0][1])
            assert visible.project_id == ids[2]
            with pytest.raises(NotFoundError):
                await service.read_extraction(extractions[1][1])
            # Append-only: the runtime role holds no UPDATE/DELETE on evidence.
            for statement in (
                "UPDATE source_fragments SET text_content='rewritten'",
                "DELETE FROM source_fragments",
                "UPDATE source_extractions SET coverage='{}'::jsonb",
            ):
                with pytest.raises(ProgrammingError):
                    async with session.begin_nested():
                        await session.execute(text(statement))
