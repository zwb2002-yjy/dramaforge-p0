"""Research analysis tables under real RLS, append-only grants and pointer FK."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.assets.research_analysis_models import ResearchAnalysis
from app.director.turn_models import DirectorTurn
from app.shared.db import set_rls_context
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_research_analysis_rls_append_only_and_pointer_fk():
    dbname = f"dramaforge_analysis_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = InMemoryObjectStore()
    try:
        _alembic(dbname)
        async with factory() as session:
            actor = User(
                email=f"analysis-{uuid4()}@example.com", display_name="Owner", password_hash="x"
            )
            session.add(actor)
            await session.flush()
            workspace = Workspace(name="Analysis", owner_user_id=actor.id)
            session.add(workspace)
            await session.flush()
            projects = [
                Project(workspace_id=workspace.id, name=name, aspect_ratio="16:9", budget_limit=0)
                for name in ("First", "Second")
            ]
            session.add_all(projects)
            await session.commit()
            actor_id, workspace_id = actor.id, workspace.id
            project_id, other_project = [project.id for project in projects]

        async def parsed_revision(project: object, key: str):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(
                    session, user_id=actor_id, workspace_id=workspace_id, project_id=project
                )
                session.info["selected_workspace_id"] = workspace_id
                owner = await session.get(User, actor_id)
                assert owner is not None
                service = ProjectFileService(
                    session, store=store, actor=owner, project_id=project
                )
                revision = await service.upload(
                    filename="source.txt",
                    data=b"analysis source",
                    mime_type="text/plain",
                    request_key=key,
                )
                await session.commit()
                parsed = await service.extract(revision.id)
                await session.commit()
                return parsed.id, parsed.current_extraction_id

        revision_id, extraction_id = await parsed_revision(project_id, "analysis-source")
        _other_revision, other_extraction = await parsed_revision(other_project, "analysis-other")

        async def insert_analysis(
            project: object, revision: object, extraction: object, key: str
        ):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(
                    session, user_id=actor_id, workspace_id=workspace_id, project_id=project
                )
                session.info["selected_workspace_id"] = workspace_id
                row = await session.execute(
                    text(
                        "INSERT INTO research_analyses "
                        "(id, project_id, file_revision_id, source_extraction_id, coverage, "
                        " category_outcomes, manifest_hash, request_key, request_hash, "
                        " completed_at) "
                        "VALUES (gen_random_uuid(), :project, :revision, :extraction, "
                        "'{\"complete\": true}'::jsonb, '{}'::jsonb, :hash, :key, :hash, now()) "
                        "RETURNING id"
                    ),
                    {
                        "project": project,
                        "revision": revision,
                        "extraction": extraction,
                        "hash": "a" * 64,
                        "key": key,
                    },
                )
                analysis_id = row.scalar_one()
                await session.commit()
                return analysis_id

        analysis_id = await insert_analysis(project_id, revision_id, extraction_id, "analysis-1")
        other_analysis = await insert_analysis(
            other_project, _other_revision, other_extraction, "analysis-other"
        )

        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id
            )
            session.info["selected_workspace_id"] = workspace_id
            visible = list(await session.scalars(select(ResearchAnalysis.id)))
            assert visible == [analysis_id]
            with pytest.raises(DBAPIError, match="permission denied"):
                async with session.begin_nested():
                    await session.execute(
                        text("UPDATE research_analyses SET manifest_hash = :hash"),
                        {"hash": "b" * 64},
                    )
            # The pointer only accepts a manifest of this exact revision. The FK is
            # deferred, so force immediate checking inside the savepoint.
            with pytest.raises(DBAPIError, match="foreign key"):
                async with session.begin_nested():
                    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                    await session.execute(
                        text(
                            "UPDATE project_file_revisions SET current_analysis_id = :analysis "
                            "WHERE id = :revision"
                        ),
                        {"analysis": other_analysis, "revision": revision_id},
                    )
            await session.rollback()
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id
            )
            session.info["selected_workspace_id"] = workspace_id
            await session.execute(
                text(
                    "UPDATE project_file_revisions SET current_analysis_id = :analysis "
                    "WHERE id = :revision"
                ),
                {"analysis": analysis_id, "revision": revision_id},
            )
            await session.commit()
        async with factory() as session:
            pointer = await session.scalar(
                text(
                    "SELECT current_analysis_id FROM project_file_revisions WHERE id = :revision"
                ),
                {"revision": revision_id},
            )
            assert pointer == analysis_id
    finally:
        await engine.dispose()
        await _drop_database(dbname)


async def test_research_turn_scan_returns_only_queued_research_work():
    dbname = f"dramaforge_rscan_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = InMemoryObjectStore()
    try:
        _alembic(dbname)
        async with factory() as session:
            actor = User(
                email=f"rscan-{uuid4()}@example.com", display_name="Owner", password_hash="x"
            )
            session.add(actor)
            await session.flush()
            workspace = Workspace(name="Scan", owner_user_id=actor.id)
            session.add(workspace)
            await session.flush()
            project = Project(
                workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0
            )
            session.add(project)
            await session.commit()
            actor_id, workspace_id, project_id = actor.id, workspace.id, project.id

        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id
            )
            session.info["selected_workspace_id"] = workspace_id
            owner = await session.get(User, actor_id)
            assert owner is not None
            files = ProjectFileService(
                session, store=store, actor=owner, project_id=project_id
            )
            revision = await files.upload(
                filename="scan.txt",
                data=b"scan source",
                mime_type="text/plain",
                request_key="rscan-upload",
            )
            await session.commit()
            parsed = await files.extract(revision.id)
            await session.commit()
            from app.director.research_import import ResearchImportService, ResearchRequest

            project_row = await session.get(Project, project_id)
            assert project_row is not None
            acceptance = await ResearchImportService(session).accept(
                project=project_row,
                actor=owner,
                request=ResearchRequest(
                    file_revision_id=parsed.id,
                    source_extraction_id=parsed.current_extraction_id,
                    categories=["summary"],
                    targets=[],
                    model_identity={"model_id": "text-model-1"},
                    preview_fingerprint="f" * 64,
                    request_key="rscan-accept",
                ),
            )
            await session.commit()
            research_turn = acceptance.turn_id

        from app.shared.rls_scopes import (
            list_pending_research_turn_rls_scopes,
            resolve_research_turn_rls_scope,
        )

        async with factory() as session:
            rows = await list_pending_research_turn_rls_scopes(session, limit=10)
            assert [turn_id for turn_id, _scope in rows] == [research_turn]
            scope = await resolve_research_turn_rls_scope(session, turn_id=research_turn)
            assert scope is not None
            assert scope.project_id == project_id and scope.user_id == actor_id
        # Claiming removes it from the pending scan; a resolved id still answers.
        async with factory() as session:
            await set_rls_context(
                session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id
            )
            session.info["selected_workspace_id"] = workspace_id
            turn = await session.get(DirectorTurn, research_turn)
            assert turn is not None
            from app.director.turn_service import DirectorTurnService

            await DirectorTurnService(session).claim(
                project_id=project_id, turn_id=turn.id, expected_revision=turn.revision
            )
            await session.commit()
        async with factory() as session:
            assert await list_pending_research_turn_rls_scopes(session, limit=10) == []
            resolved = await resolve_research_turn_rls_scope(session, turn_id=research_turn)
            assert resolved is not None and resolved.project_id == project_id
    finally:
        await engine.dispose()
        await _drop_database(dbname)
