"""PostgreSQL proof for first-Owner bootstrap through the runtime role."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from app.access.projects import ProjectService
from app.access.service import AccessService
from app.director.enums import ArtifactKind
from app.director.service import DirectorService
from app.shared.db import set_rls_context
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
DB_USER = os.environ.get("TEST_PG_USER", "dramaforge")
DB_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "dramaforge")


def _pg_host() -> str:
    return os.environ.get("TEST_PG_HOST", "127.0.0.1")


def _pg_port() -> str:
    return os.environ.get("TEST_PG_PORT", "5432")


def _admin_url() -> str:
    default = f"postgresql://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/postgres"
    return os.environ.get("TEST_PG_ADMIN_URL", default)


def _pg_available() -> bool:
    try:
        engine = create_engine(
            f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}"
            f"@{_pg_host()}:{_pg_port()}/dramaforge",
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2},
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _pg_available(),
    reason=(
        "set TEST_PG_ENABLED=1 with an explicitly configured isolated PostgreSQL target"
    ),
)


@pytest.mark.asyncio
async def test_first_owner_bootstrap_survives_users_force_rls() -> None:
    database_name = f"df_bootstrap_{uuid.uuid4().hex[:12]}"
    runtime_password = f"df-runtime-{uuid.uuid4().hex}"
    admin_url = _admin_url()
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin.close()

    database_url = (
        f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}"
        f"@{_pg_host()}:{_pg_port()}/{database_name}"
    )
    try:
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(BACKEND),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(
                f"ALTER ROLE dramaforge_app LOGIN PASSWORD '{runtime_password}'"
            )
        finally:
            await admin.close()

        runtime_database_url = (
            "postgresql+asyncpg://dramaforge_app:"
            f"{runtime_password}@{_pg_host()}:{_pg_port()}/{database_name}"
        )
        engine = create_async_engine(runtime_database_url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as first_session:
                first_service = AccessService(first_session)
                initialized, available = await first_service.registration_status(
                    public_registration_enabled=False
                )
                assert initialized is False and available is True
                owner = await first_service.register(
                    email=f"bootstrap-{uuid.uuid4().hex}@example.invalid",
                    password="password123",
                    display_name="Bootstrap Owner",
                    public_registration_enabled=False,
                )
                workspace = await first_service.create_workspace(
                    name="Post-bootstrap workspace",
                    owner=owner,
                )
                assert workspace.owner_user_id == owner.id

            async with factory() as workspace_session:
                await set_rls_context(
                    workspace_session,
                    user_id=owner.id,
                    workspace_id=workspace.id,
                )
                renamed = await AccessService(workspace_session).rename_workspace(
                    workspace_id=workspace.id,
                    name="Renamed workspace",
                    actor=owner,
                )
                assert renamed.name == "Renamed workspace"

            async with factory() as project_session:
                await set_rls_context(
                    project_session,
                    user_id=owner.id,
                    workspace_id=workspace.id,
                )
                project = await ProjectService(project_session).create_project(
                    workspace_id=workspace.id,
                    name="Director bootstrap project",
                    aspect_ratio="9:16",
                    actor=owner,
                )
                await project_session.commit()

            async with factory() as workflow_session:
                await set_rls_context(
                    workflow_session,
                    user_id=owner.id,
                    workspace_id=workspace.id,
                    project_id=project.id,
                )
                workflow = await DirectorService(workflow_session).start_workflow(
                    project_id=project.id,
                    actor=owner,
                )
                assert workflow.project_id == project.id

            async with factory() as artifact_session:
                await set_rls_context(
                    artifact_session,
                    user_id=owner.id,
                    workspace_id=workspace.id,
                    project_id=project.id,
                )
                artifact = await DirectorService(
                    artifact_session
                ).publish_artifact_version(
                    project_id=project.id,
                    actor=owner,
                    artifact_kind=ArtifactKind.STORY_CORE,
                    payload={
                        "selected_concept_id": "bootstrap-concept",
                        "theme": "Courage",
                        "core_conflict": "The lead must decide whether to face the truth.",
                        "emotional_direction": "Uncertainty to resolve",
                        "ending": "The lead chooses to move forward.",
                        "characters": [
                            {
                                "name": "Lin",
                                "identity": "A fictional designer",
                                "desire": "Tell the truth",
                                "fear_or_cost": "Losing a relationship",
                            }
                        ],
                    },
                    source_kind="user",
                )
                assert artifact.workflow_run_id == workflow.id

            async with factory() as second_session:
                initialized, available = await AccessService(
                    second_session
                ).registration_status(public_registration_enabled=False)
                assert initialized is True and available is False

            async with factory() as login_session:
                authenticated = await AccessService(login_session).authenticate(
                    email=owner.email,
                    password="password123",
                )
                assert authenticated.id == owner.id
        finally:
            await engine.dispose()
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            await admin.execute(
                "ALTER ROLE dramaforge_app NOLOGIN NOINHERIT NOBYPASSRLS PASSWORD NULL"
            )
        finally:
            await admin.close()
