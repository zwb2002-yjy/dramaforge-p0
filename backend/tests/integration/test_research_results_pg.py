"""Research tables under real RLS, append-only grants and the current-pointer guard."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.research import ResearchConflictError, ResearchService
from app.assets.research_models import ResearchResultRevision
from app.shared.db import set_rls_context
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_research_rls_append_only_and_current_pointer_guard():
    dbname = f"dramaforge_research_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        _alembic(dbname)
        async with factory() as session:
            actor = User(
                email=f"research-{uuid4()}@example.com", display_name="Owner", password_hash="x"
            )
            session.add(actor)
            await session.flush()
            workspace = Workspace(name="Research", owner_user_id=actor.id)
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

        async def create(project: object, key: str, name: str):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(
                    session, user_id=actor_id, workspace_id=workspace_id, project_id=project
                )
                session.info["selected_workspace_id"] = workspace_id
                owner = await session.get(User, actor_id)
                assert owner is not None
                service = ResearchService(session, actor=owner, project_id=project)
                receipt = await service.create_result(
                    kind="place",
                    body={"schema_version": 1, "display_name": name},
                    verification="unverified",
                    citations=[],
                    request_key=key,
                )
                await session.commit()
                return receipt

        created = await create(project_id, "place-1", "东岸渡口")
        await create(other_project, "place-other", "西岸码头")

        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id
            )
            session.info["selected_workspace_id"] = workspace_id
            owner = await session.get(User, actor_id)
            assert owner is not None
            service = ResearchService(session, actor=owner, project_id=project_id)
            # RLS hides the other project's result even with an unscoped select.
            assert await session.scalar(select(ResearchResultRevision)) is not None
            results, total = await service.list_results()
            assert total == 1 and results[0].id == created.result_id
            found, total = await service.list_results(query="渡口")
            assert total == 1 and found[0].id == created.result_id
            # Appending is append-only: updating a revision is denied by the grant.
            with pytest.raises(DBAPIError, match="permission denied"):
                async with session.begin_nested():
                    await session.execute(
                        update(ResearchResultRevision)
                        .where(ResearchResultRevision.project_id == project_id)
                        .values(verification="corroborated")
                    )
            # Cross-project write is refused by the RLS WITH CHECK.
            with pytest.raises(DBAPIError, match="row-level security"):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "INSERT INTO research_results (id, project_id, kind, version) "
                            "VALUES (gen_random_uuid(), :project, 'summary', 1)"
                        ),
                        {"project": other_project},
                    )
            await session.rollback()

        # The current pointer may only name an applied revision of the same result.
        async with factory() as session:
            candidate = ResearchResultRevision(
                project_id=project_id,
                result_id=created.result_id,
                number=2,
                origin="user",
                body={"schema_version": 1, "display_name": "候选"},
                content_hash="0" * 64,
                verification="unverified",
                applied_result_version=None,
                request_key="candidate-1",
                request_hash="0" * 64,
            )
            session.add(candidate)
            await session.commit()
            candidate_id = candidate.id
            with pytest.raises(DBAPIError, match="RESEARCH_CURRENT_UNAPPLIED_REVISION"):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "UPDATE research_results SET current_revision_id = :candidate "
                            "WHERE id = :result"
                        ),
                        {"candidate": candidate_id, "result": created.result_id},
                    )
            with pytest.raises(DBAPIError, match="RESEARCH_RESULT_VERSION_SKIP"):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "UPDATE research_results SET version = version + 3 "
                            "WHERE id = :result"
                        ),
                        {"result": created.result_id},
                    )
            await session.rollback()

        # Concurrent corrections from the same base: exactly one wins the CAS.
        async def correct(key: str):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(
                    session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id
                )
                session.info["selected_workspace_id"] = workspace_id
                owner = await session.get(User, actor_id)
                assert owner is not None
                service = ResearchService(session, actor=owner, project_id=project_id)
                try:
                    receipt = await service.append_revision(
                        created.result_id,
                        expected_version=2,
                        base_revision_id=created.revision_id,
                        body={"schema_version": 1, "display_name": key},
                        verification="unverified",
                        citations=[],
                        request_key=key,
                    )
                    await session.commit()
                    return receipt.revision_id
                except ResearchConflictError as error:
                    await session.rollback()
                    return error.code

        outcomes = await asyncio.gather(correct("concurrent-a"), correct("concurrent-b"))
        assert sorted(str(item) for item in outcomes).count("RESEARCH_STALE_VERSION") == 1
        winners = [item for item in outcomes if item != "RESEARCH_STALE_VERSION"]
        assert len(winners) == 1
    finally:
        await engine.dispose()
        await _drop_database(dbname)
