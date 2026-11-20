"""Egress policy/destination RLS, append-only grants and head integrity (PG)."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.egress_models import (
    ProjectEgressPolicyHead,
    ProjectEgressPolicyRevision,
    ProviderDestinationRevision,
)
from app.access.models import Project, User, Workspace
from app.access.project_data_policy import ProjectDataPolicy
from app.shared.db import set_rls_context
from pg_support import alembic_head
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
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
async def egress_database():
    name = f"dramaforge_egress_{uuid4().hex[:10]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        _alembic(name)
        yield name, engine, factory
    finally:
        await engine.dispose()
        await _drop_database(name)


async def test_policy_scope_append_only_grants_and_head_composite_fk():
    async with egress_database() as (name, engine, factory):
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
            foreign = Project(
                workspace_id=foreign_workspace.id, name="丙", aspect_ratio="16:9",
                budget_limit=0, work_type="single_comic",
            )
            session.add_all([first, second, foreign])
            await session.commit()
            ids = {
                "owner": owner.id, "other": other.id, "workspace": workspace.id,
                "foreign_workspace": foreign_workspace.id, "first": first.id,
                "second": second.id, "foreign": foreign.id,
            }
            session.info["selected_workspace_id"] = workspace.id
            revision = await ProjectDataPolicy(
                session, actor=owner, project=first,
            ).put(
                expected_revision=0, mode="local_only",
                allowed_destination_revision_ids=[], allowed_purposes=[],
            )
            await session.commit()
            revision_id = revision.id
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["owner"], workspace_id=ids["workspace"],
                project_id=ids["second"],
            )
            assert await session.scalar(select(func.count(ProjectEgressPolicyRevision.id))) == 0
            assert await session.scalar(select(func.count(ProjectEgressPolicyHead.project_id))) == 0
            await session.rollback()
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["owner"], workspace_id=ids["workspace"],
                project_id=ids["first"],
            )
            assert await session.scalar(select(func.count(ProjectEgressPolicyRevision.id))) == 1
            head = await session.scalar(select(ProjectEgressPolicyHead))
            assert head is not None and head.current_revision_id == revision_id
            # Revisions are append-only; the head may move but never be deleted.
            for statement in (
                "UPDATE project_egress_policy_revisions SET mode = 'current'",
                "DELETE FROM project_egress_policy_revisions",
                "DELETE FROM project_egress_policy_heads",
            ):
                with pytest.raises(ProgrammingError):
                    async with session.begin_nested():
                        await session.execute(text(statement))
            async with session.begin_nested():
                await session.execute(text("UPDATE project_egress_policy_heads SET revision = 2"))
            await session.rollback()
        async with factory() as session:
            # A head can never point at another project's revision (deferred FK).
            with pytest.raises((IntegrityError, DBAPIError)):
                session.add(ProjectEgressPolicyHead(
                    project_id=ids["second"], current_revision_id=revision_id, revision=1,
                ))
                await session.flush()
                await session.commit()
            await session.rollback()


async def test_destination_workspace_scope_and_append_only():
    async with egress_database() as (name, engine, factory):
        async with factory() as session:
            owner = User(email=f"{uuid4()}@example.com", display_name="O", password_hash="x")
            other = User(email=f"{uuid4()}@example.com", display_name="X", password_hash="x")
            session.add_all([owner, other])
            await session.flush()
            workspace = Workspace(name="机构", owner_user_id=owner.id)
            foreign_workspace = Workspace(name="其它", owner_user_id=other.id)
            session.add_all([workspace, foreign_workspace])
            await session.flush()
            row = ProviderDestinationRevision(
                workspace_id=workspace.id, binding_ref=str(uuid4()), revision=1,
                origin_expected_revision=0, upstream_origin="http://litellm-proxy:4000",
                processing_location="local", purposes=["director_text"],
                declaration_hash="a" * 64, configuration_hash="b" * 64,
                route_manifest={"schema_version": 1}, location_evidence={},
                created_by=owner.id,
            )
            session.add(row)
            await session.commit()
            ids = {
                "owner": owner.id, "other": other.id,
                "workspace": workspace.id, "foreign_workspace": foreign_workspace.id,
                "destination": row.id,
            }
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["other"], workspace_id=ids["foreign_workspace"],
                project_id=uuid4(),
            )
            assert await session.scalar(
                select(func.count(ProviderDestinationRevision.id))
            ) == 0
            await session.rollback()
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["owner"], workspace_id=ids["workspace"], project_id=uuid4(),
            )
            assert await session.scalar(
                select(func.count(ProviderDestinationRevision.id))
            ) == 1
            for statement in (
                "UPDATE provider_destination_revisions SET processing_location = 'external'",
                "DELETE FROM provider_destination_revisions",
            ):
                with pytest.raises(ProgrammingError):
                    async with session.begin_nested():
                        await session.execute(text(statement))
            await session.rollback()


async def test_populated_egress_history_blocks_downgrade():
    name = f"dramaforge_egress_mig_{uuid4().hex[:8]}"
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
            await ProjectDataPolicy(session, actor=owner, project=project).put(
                expected_revision=0, mode="current",
                allowed_destination_revision_ids=[], allowed_purposes=[],
            )
            await session.commit()
        refused = migration(name, "downgrade", "20261117_0102")
        assert refused.returncode != 0
        assert "EGRESS_POLICY_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE" in refused.stderr
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == alembic_head()
        checked = migration(name, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
    finally:
        await engine.dispose()
        await _drop_database(name)


async def test_director_submission_cannot_overtake_uncommitted_local_policy():
    import asyncio

    from app.director.text_transport import director_egress_decision

    async with egress_database() as (_, __, factory):
        async with factory() as writer, factory() as reader:
            owner = User(email=f"{uuid4()}@example.com", display_name="Owner", password_hash="x")
            writer.add(owner)
            await writer.flush()
            workspace = Workspace(name="fixture", owner_user_id=owner.id)
            writer.add(workspace)
            await writer.flush()
            project = Project(workspace_id=workspace.id, name="灯会", aspect_ratio="16:9",
                              budget_limit=0, work_type="single_comic")
            writer.add(project)
            await writer.commit()
            await ProjectDataPolicy(writer, actor=owner, project=project).put(
                expected_revision=0, mode="local_only",
                allowed_destination_revision_ids=[], allowed_purposes=[],
            )
            await reader.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(reader, user_id=owner.id, workspace_id=workspace.id,
                                  project_id=project.id)
            visible = await reader.get(Project, project.id)
            assert visible is not None
            task = asyncio.create_task(director_egress_decision(reader, project=visible, resolution={}))
            try:
                done, _pending = await asyncio.wait({task}, timeout=0.2)
                assert not done
            finally:
                await writer.commit()
                decision = await asyncio.wait_for(task, timeout=5)
            assert not decision.allowed and decision.reason_code == "EGRESS_LOCAL_ONLY"
            assert decision.policy_revision == 1
