"""PostgreSQL proof for first-Owner bootstrap outside users FORCE RLS."""

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
DEFAULT_ADMIN = "postgresql://dramaforge:dramaforge@127.0.0.1:5432/postgres"


def _pg_available() -> bool:
    try:
        engine = create_engine(
            "postgresql+psycopg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge",
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
    admin_url = os.environ.get("TEST_PG_ADMIN_URL", DEFAULT_ADMIN)
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin.close()

    database_url = (
        "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/"
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

        engine = create_async_engine(database_url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as first_session:
                first = AccessService(first_session)
                initialized, available = await first.registration_status(
                    public_registration_enabled=False
                )
                assert initialized is False and available is True
                await first.register(
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
        finally:
            await engine.dispose()
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        finally:
            await admin.close()
