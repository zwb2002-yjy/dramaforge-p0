"""Real RLS, shared writer locks and guarded project-intent migration proof."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.api.v1.projects import ProjectUpdate, update_project
from app.assets.models import Episode, ScriptDocument
from app.assets.script_import import import_script
from app.director.proposal_commands import ProposalCommandError, ProposalCommandRegistry
from app.events.models import EventLog, OutboxEvent
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, NotFoundError
from pg_support import alembic_head
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

BACKEND = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def project_database():
    name = f"dramaforge_institution_{uuid4().hex[:10]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        _alembic(name)
        async with factory() as session:
            owner = User(email=f"{uuid4()}@example.com", display_name="Owner", password_hash="x")
            other = User(email=f"{uuid4()}@example.com", display_name="Other", password_hash="x")
            session.add_all([owner, other])
            await session.flush()
            workspace = Workspace(name="机构", owner_user_id=owner.id)
            foreign_workspace = Workspace(name="其它机构", owner_user_id=other.id)
            session.add_all([workspace, foreign_workspace])
            await session.flush()
            project = await ProjectService(session).create_project(
                workspace_id=workspace.id,
                actor=owner,
                name="单集作品",
                aspect_ratio="16:9",
                work_type="single_comic",
            )
            await session.commit()
            ids = (owner.id, workspace.id, project.id, other.id, foreign_workspace.id)
        yield factory, ids
    finally:
        await engine.dispose()
        await _drop_database(name)


async def app_scope(session, user_id, workspace_id, project_id):
    await session.execute(text("SET LOCAL ROLE dramaforge_app"))
    await set_rls_context(
        session,
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    session.info["selected_workspace_id"] = workspace_id
    actor = await session.get(User, user_id)
    assert actor is not None
    return actor


@pytest.mark.parametrize("writers", [("import", "import"), ("import", "apply"), ("apply", "apply")])
async def test_single_comic_concurrent_writers_have_one_episode_winner(writers):
    async with project_database() as (factory, ids):
        owner_id, workspace_id, project_id, _, _ = ids
        ready = asyncio.Queue()
        start = asyncio.Event()

        async def write(kind, number):
            async with factory() as session:
                actor = await app_scope(session, owner_id, workspace_id, project_id)
                await ready.put(number)
                await start.wait()
                try:
                    if kind == "import":
                        await import_script(
                            session,
                            project_id=project_id,
                            actor_id=owner_id,
                            actor=actor,
                            filename=f"episode-{number}.md",
                            text=(
                                f"# Episode {number} — Synthetic\n"
                                "## Scene 1 — Square / day\nSynthetic place\n"
                                "### Shot 1 — medium\nvisual: Synthetic scene\ndialogue: Hello\n"
                            ),
                        )
                    else:
                        await ProposalCommandRegistry(session, actor_id=owner_id).apply(
                            project_id=project_id,
                            command="story.upsert_episode",
                            payload={"episode_number": number, "title": "Synthetic"},
                            expected_target_version=None,
                        )
                    await session.commit()
                    return "accepted", kind
                except (ConflictError, ProposalCommandError) as exc:
                    assert exc.details["code"] == "PROJECT_STRUCTURE_CONFLICT"
                    await session.rollback()
                    return "refused", kind

        async with asyncio.TaskGroup() as tasks:
            attempts = [tasks.create_task(write(kind, i + 1)) for i, kind in enumerate(writers)]
            await asyncio.wait_for(ready.get(), timeout=10)
            await asyncio.wait_for(ready.get(), timeout=10)
            start.set()
        outcomes = [attempt.result() for attempt in attempts]
        assert sorted(status for status, _ in outcomes) == ["accepted", "refused"]
        winning_kind = next(kind for status, kind in outcomes if status == "accepted")
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Episode)) == 1
            assert await session.scalar(select(func.count()).select_from(ScriptDocument)) == int(
                winning_kind == "import"
            )


async def test_project_cas_event_and_foreign_owner_refusal_with_real_rls():
    async with project_database() as (factory, ids):
        owner_id, workspace_id, project_id, other_id, foreign_workspace_id = ids
        async with factory() as session:
            owner = await session.get(User, owner_id)
            other = await session.get(User, other_id)
            sibling_workspace = Workspace(name="第二工作空间", owner_user_id=owner_id)
            session.add(sibling_workspace)
            await session.flush()
            sibling = await ProjectService(session).create_project(
                workspace_id=sibling_workspace.id,
                actor=owner,
                name="宣传片",
                aspect_ratio="16:9",
                work_type="animation_promo",
            )
            foreign = await ProjectService(session).create_project(
                workspace_id=foreign_workspace_id,
                actor=other,
                name="他人的连续剧",
                aspect_ratio="16:9",
                work_type="serial_comic",
            )
            await session.commit()
            sibling_workspace_id, sibling_id, foreign_id = (
                sibling_workspace.id,
                sibling.id,
                foreign.id,
            )
        ready = asyncio.Queue()
        start = asyncio.Event()

        async def update(goal):
            async with factory() as session:
                actor = await app_scope(session, owner_id, workspace_id, project_id)
                await ready.put(goal)
                await start.wait()
                try:
                    result = await update_project(
                        project_id=project_id,
                        user=actor,
                        session=session,
                        _=None,
                        body=ProjectUpdate(expected_version=1, creative_goal=goal),
                    )
                    assert result.version == 2
                    return "accepted"
                except ConflictError as exc:
                    assert exc.details["code"] == "PROJECT_VERSION_CONFLICT"
                    await session.rollback()
                    return "refused"

        async with asyncio.TaskGroup() as tasks:
            attempts = [tasks.create_task(update(goal)) for goal in ("first", "second")]
            await asyncio.wait_for(ready.get(), timeout=10)
            await asyncio.wait_for(ready.get(), timeout=10)
            start.set()
        assert sorted(task.result() for task in attempts) == ["accepted", "refused"]
        async with factory() as session:
            project = await session.get(Project, project_id)
            assert project.version == 2 and project.creative_goal in {"first", "second"}
            event = (await session.scalars(select(EventLog))).one()
            outbox = (await session.scalars(select(OutboxEvent))).one()
            assert event.event_id == outbox.event_id
            assert event.payload["notice"]["project_version"] == 2
        for selected, visible, hidden in (
            (workspace_id, project_id, sibling_id),
            (sibling_workspace_id, sibling_id, project_id),
        ):
            async with factory() as session:
                actor = await app_scope(session, owner_id, selected, visible)
                service = ProjectService(session)
                assert (
                    await service.get_project_for_owner(project_id=visible, actor=actor)
                ).id == visible
                with pytest.raises(NotFoundError):
                    await service.get_project_for_owner(project_id=hidden, actor=actor)
                with pytest.raises(NotFoundError):
                    await service.get_project_for_owner(project_id=foreign_id, actor=actor)
        async with factory() as session:
            # Real requests enter workspace-scoped and rebind per project; bind the
            # foreign owner's context to their own project exactly like the owner
            # loop above, not to the inaccessible project under test.
            actor = await app_scope(session, other_id, foreign_workspace_id, foreign_id)
            assert await session.get(Project, project_id) is None
            visible = await ProjectService(session).get_project_for_owner(
                project_id=foreign_id,
                actor=actor,
            )
            assert visible.id == foreign_id
            with pytest.raises(NotFoundError):
                await ProjectService(session).update_project(
                    project_id=project_id,
                    actor=actor,
                    expected_version=2,
                    updates={"creative_goal": "forbidden"},
                )


def migration(name, direction, target=None):
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, *([target] if target is not None else [])],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": _async_url(name)},
        capture_output=True,
        text=True,
        check=False,
    )


async def test_legacy_type_remains_unconfirmed_and_populated_downgrade_is_refused():
    name = f"dramaforge_intent_migration_{uuid4().hex[:8]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    try:
        result = migration(name, "upgrade", "20261113_0099")
        assert result.returncode == 0, result.stderr
        user_id, workspace_id, project_id = uuid4(), uuid4(), uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users(id,email,display_name,password_hash) "
                    "VALUES (:id,:email,'Old','x')"
                ),
                {"id": user_id, "email": f"{uuid4()}@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO workspaces(id,owner_user_id,name) "
                    "VALUES (:id,:owner,'Old workspace')"
                ),
                {"id": workspace_id, "owner": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects(id,workspace_id,name,aspect_ratio,budget_limit) "
                    "VALUES (:id,:workspace,'Legacy','16:9',0)"
                ),
                {"id": project_id, "workspace": workspace_id},
            )
        _alembic(name)
        async with engine.begin() as connection:
            row = (
                await connection.execute(
                    text("SELECT work_type,creative_goal,audience FROM projects WHERE id=:id"),
                    {"id": project_id},
                )
            ).one()
            assert tuple(row) == (None, "", "")
            for invalid in (
                "planned_duration_seconds='NaN'",
                "planned_duration_seconds=0",
                "planned_duration_seconds=-1",
                "work_type='unknown'",
                "work_type='single_comic',planned_episode_count=2",
                "work_type='serial_comic',planned_episode_count=1",
                "work_type='animation_promo',planned_episode_count=1",
                "audience=repeat('x',2001)",
                "creative_goal=repeat('x',16001)",
            ):
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():
                        await connection.execute(text(f"UPDATE projects SET {invalid}"))
            await connection.execute(
                text("UPDATE projects SET creative_goal='must preserve' WHERE id=:id"),
                {"id": project_id},
            )
        refused = migration(name, "downgrade", "20261113_0099")
        assert refused.returncode != 0
        assert "INSTITUTION_INTENT_DOWNGRADE_REQUIRES_EMPTY_FIELDS" in refused.stderr
        async with engine.begin() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == alembic_head()
            assert (
                await connection.execute(text("SELECT creative_goal FROM projects"))
            ).scalar_one() == "must preserve"
            # Explicitly discard only this isolated synthetic intent for empty-field rollback proof.
            await connection.execute(text("UPDATE projects SET creative_goal=''"))
        # Even cleared fields cannot discard the new notice contract on rollback.
        from app.contracts.domain_events import ProjectChanged
        from app.production.application.events import append_production_notice

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            event_id = await append_production_notice(
                session,
                project_id=project_id,
                actor_id=user_id,
                notice=ProjectChanged(project_id=project_id, project_version=1),
            )
            await session.commit()
        refused_event = migration(name, "downgrade", "20261113_0099")
        assert refused_event.returncode != 0
        assert "INSTITUTION_INTENT_DOWNGRADE_REQUIRES_EMPTY_FIELDS" in refused_event.stderr
        async with engine.begin() as connection:
            # Only this owned synthetic notice is removed for the empty rollback case.
            await connection.execute(
                text("DELETE FROM outbox_events WHERE event_id=:id"), {"id": event_id}
            )
            await connection.execute(
                text("DELETE FROM event_log WHERE event_id=:id"), {"id": event_id}
            )
        rolled_back = migration(name, "downgrade", "20261113_0099")
        assert rolled_back.returncode == 0, rolled_back.stderr
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT name FROM projects"))
            ).scalar_one() == "Legacy"
        _alembic(name)
        checked = migration(name, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
    finally:
        await engine.dispose()
        await _drop_database(name)
