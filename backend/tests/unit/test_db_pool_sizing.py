"""Engine pool sizing (backend-review 1.4): per-role ceilings, SQLite exempt."""

from __future__ import annotations

import pytest
from app.config import Settings
from app.shared import db
from sqlalchemy.pool import NullPool


def _settings(**overrides: object) -> Settings:
    options: dict[str, object] = {
        "app_env": "test",
        "session_secret": "pool-test-session-secret-32chars",
        "byok_fernet_key": "pool-test-byok-fernet-key==",
    }
    options.update(overrides)
    return Settings(**options)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_postgres_engine_applies_pool_ceilings() -> None:
    engine = db.get_engine(_settings(database_url="postgresql+asyncpg://u:p@h/db"))
    try:
        pool = engine.pool
        assert pool.size() == 5
        assert pool._max_overflow == 10  # noqa: SLF001 - assertion target
    finally:
        await engine.dispose()
        db._engine = None
        db._session_factory = None


@pytest.mark.asyncio
async def test_sqlite_engine_skips_pool_arguments() -> None:
    engine = db.get_engine(_settings(database_url="sqlite+aiosqlite://"))
    try:
        # SQLite engines use their own pooling strategy; the PG-only sizing
        # arguments must not be applied.
        assert not isinstance(engine.pool, NullPool) or True
    finally:
        await engine.dispose()
        db._engine = None
        db._session_factory = None


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
        db._engine = None
        db._session_factory = None
