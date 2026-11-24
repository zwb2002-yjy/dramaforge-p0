"""Nonempty retired evidence blocks the readonly migration preflight."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from app.shared.migration_safety import RETIRED_TABLES
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_retired_table_nonempty_is_reported_without_delete_or_write():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "migration_audit", root / "scripts/audit_model_migration.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dbname = f"model_preflight_{uuid4().hex[:12]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE model_publication_events (id integer)"))
            await connection.execute(text("INSERT INTO model_publication_events VALUES (1)"))
        async with async_sessionmaker(engine)() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            report = await module.inspect_retired_tables(session)
            assert report["blocked_nonempty_tables"] == ["model_publication_events"]
            assert not report["backup_restore_verified"]
            assert not report["destructive_migration_applied"]
            assert await session.scalar(text("SELECT count(*) FROM model_publication_events")) == 1
            await session.rollback()
    finally:
        await engine.dispose()
        await _drop_database(dbname)


@pytest.mark.parametrize("table", RETIRED_TABLES)
async def test_normal_alembic_upgrade_blocks_each_nonempty_retired_table(table):
    dbname = f"model_upgrade_block_{uuid4().hex[:12]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32))"))
            await connection.execute(text("INSERT INTO alembic_version VALUES ('20261007_0083')"))
            await connection.execute(text(f'CREATE TABLE "{table}" (id integer)'))
            await connection.execute(text(f'INSERT INTO "{table}" VALUES (1)'))
        env = {**os.environ, "DATABASE_URL": _async_url(dbname)}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "MODEL_MIGRATION_EVIDENCE_NOT_ARCHIVED" in result.stderr
        assert table in result.stderr
        async with engine.connect() as connection:
            assert await connection.scalar(text(f'SELECT count(*) FROM "{table}"')) == 1
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20261007_0083"
            )
    finally:
        await engine.dispose()
        await _drop_database(dbname)
