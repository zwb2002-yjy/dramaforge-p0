"""D5 additive migration can roll down empty state and reapply cleanly."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from test_director_turn_lifecycle_pg import (
    _admin_url,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

BACKEND = Path(__file__).resolve().parents[2]


def _migrate(dbname: str, direction: str, target: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", direction, target],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": _async_url(dbname)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_director_runtime_migration_round_trip() -> None:
    dbname = f"dramaforge_d5_migration_{uuid4().hex[:8]}"
    await _create_database(dbname)
    try:
        _migrate(dbname, "upgrade", "head")
        connection = await asyncpg.connect(_admin_url().rsplit("/", 1)[0] + f"/{dbname}")
        try:
            assert await connection.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == "20260910_0066"
            columns = {
                row["column_name"]
                for row in await connection.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='director_turns'"
                )
            }
            assert {
                "engine_version",
                "state_schema_version",
                "runtime_execution_id",
                "runtime_revision",
            } <= columns
            assert await connection.fetchval(
                "SELECT count(*) FROM director_runtime_checkpoints.checkpoint_migrations"
            ) == 10
            policies = await connection.fetchval(
                "SELECT count(*) FROM pg_policies "
                "WHERE schemaname='director_runtime_checkpoints'"
            )
            assert policies == 3
        finally:
            await connection.close()

        _migrate(dbname, "downgrade", "20260910_0064")
        connection = await asyncpg.connect(_admin_url().rsplit("/", 1)[0] + f"/{dbname}")
        try:
            assert await connection.fetchval(
                "SELECT to_regnamespace('director_runtime_checkpoints')"
            ) is None
            assert await connection.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='director_turns' AND column_name='runtime_execution_id'"
            ) == 0
        finally:
            await connection.close()

        _migrate(dbname, "upgrade", "head")
        connection = await asyncpg.connect(_admin_url().rsplit("/", 1)[0] + f"/{dbname}")
        try:
            assert await connection.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == "20260910_0066"
        finally:
            await connection.close()
    finally:
        await _drop_database(dbname)
