"""Engine pool sizing (backend-review 1.4): per-role ceilings, SQLite exempt."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings
from app.shared import db
from sqlalchemy.pool import AsyncAdaptedQueuePool, StaticPool


def _settings(**overrides: object) -> Settings:
    options: dict[str, object] = {
        "app_env": "test",
        "session_secret": "pool-test-session-secret-32chars",
        "byok_fernet_key": "pool-test-byok-fernet-key==",
    }
    options.update(overrides)
    return Settings(**options)  # type: ignore[arg-type]


def _reset_engine() -> None:
    db._engine = None
    db._session_factory = None


@pytest.mark.asyncio
async def test_postgres_engine_applies_pool_ceilings() -> None:
    engine = db.get_engine(_settings(database_url="postgresql+asyncpg://u:p@h/db"))
    try:
        pool = engine.pool
        assert pool.size() == 5
        assert pool._max_overflow == 10  # noqa: SLF001 - assertion target
    finally:
        await engine.dispose()
        _reset_engine()


@pytest.mark.asyncio
async def test_sqlite_engine_skips_pool_arguments(tmp_path: Path) -> None:
    # The PG-only sizing arguments must not reach the SQLite engine. A
    # file-backed SQLite engine keeps SQLAlchemy's own default QueuePool
    # sizing (5 / 10) even when the settings state 37 / 38, which proves the
    # kwargs were skipped rather than applied.
    engine = db.get_engine(
        _settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'pool-sizing.db'}",
            db_pool_size=37,
            db_max_overflow=38,
            db_pool_timeout_seconds=7,
            db_pool_recycle_seconds=61,
        )
    )
    try:
        assert engine.dialect.name == "sqlite"
        pool = engine.pool
        assert isinstance(pool, AsyncAdaptedQueuePool)
        assert pool.size() == 5
        assert pool._max_overflow == 10  # noqa: SLF001 - assertion target
        assert pool.timeout() == 30
        assert pool._recycle == -1  # noqa: SLF001 - SQLAlchemy defaults, not PG settings
    finally:
        await engine.dispose()
        _reset_engine()


@pytest.mark.asyncio
async def test_sqlite_memory_engine_uses_its_own_pool() -> None:
    # In-memory SQLite uses a single shared connection (StaticPool); the
    # QueuePool sizing arguments would be meaningless there.
    engine = db.get_engine(
        _settings(
            database_url="sqlite+aiosqlite://",
            db_pool_size=37,
        )
    )
    try:
        assert engine.dialect.name == "sqlite"
        assert isinstance(engine.pool, StaticPool)
    finally:
        await engine.dispose()
        _reset_engine()


@pytest.mark.asyncio
async def test_role_overrides_reach_the_engine() -> None:
    engine = db.get_engine(
        _settings(
            database_url="postgresql+asyncpg://u:p@h/db",
            db_pool_size=20,
            db_max_overflow=10,
        )
    )
    try:
        assert engine.pool.size() == 20
        assert engine.pool._max_overflow == 10  # noqa: SLF001
    finally:
        await engine.dispose()
        _reset_engine()
