"""PostgreSQL proof for first-Owner bootstrap through the runtime role."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from app.access.service import AccessService
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]


def _pg_host() -> str:
    return os.environ.get("TEST_PG_HOST", "127.0.0.1")


def _pg_port() -> str:
    return os.environ.get("TEST_PG_PORT", "5432")


def _admin_url() -> str:
    default = (
        "postgresql://dramaforge:dramaforge"
        f"@{_pg_host()}:{_pg_port()}/postgres"
    )
    return os.environ.get("TEST_PG_ADMIN_URL", default)


def _pg_available() -> bool:
    try:
        engine = create_engine(
            "postgresql+psycopg://dramaforge:dramaforge"
            f"@{_pg_host()}:{_pg_port()}/dramaforge",
            pool_pre_ping=True,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="PostgreSQL not reachable; start docker compose postgres"
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
        "postgresql+asyncpg://dramaforge:dramaforge"
        f"@{_pg_host()}:{_pg_port()}/"
        f"{database_name}"
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
