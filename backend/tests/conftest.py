"""Pytest fixtures for the backend package."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure test-safe defaults before importing the app.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-32chars-min")
os.environ.setdefault("BYOK_FERNET_KEY", "test-byok-fernet-key-replace==")

from app.access import models as _access_models  # noqa: E402,F401
from app.config import clear_settings_cache, get_settings  # noqa: E402
from app.creation import models as _creation_models  # noqa: E402,F401
from app.delivery import models as _delivery_models  # noqa: E402,F401
from app.events import models as _event_models  # noqa: E402,F401
from app.execution import models as _execution_models  # noqa: E402,F401
from app.main import create_app  # noqa: E402
from app.production import models as _production_models  # noqa: E402,F401
from app.shared.base import Base  # noqa: E402
from app.shared.db import get_session  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """App client with in-memory SQLite session (functional path only — not RLS)."""
    clear_settings_cache()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    import asyncio

    asyncio.get_event_loop().run_until_complete(_prepare())

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app(get_settings())
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.get_event_loop().run_until_complete(engine.dispose())


@pytest.fixture
def bare_client() -> Iterator[TestClient]:
    """Client without DB override (for pure routing/error tests that need no DB)."""
    clear_settings_cache()
    app = create_app(get_settings())
    with TestClient(app) as test_client:
        yield test_client
