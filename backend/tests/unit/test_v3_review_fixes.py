"""V3 review-gate fixes (1.md): BLOCK-1 race recovery, HIGH-3 transport id,
HIGH-4 manifest selection.

The BLOCK-1 concurrent-race test runs at the service level in a single event
loop — the API TestClient reuses a StaticPool connection across per-request
event loops, which a rollback-then-query cannot survive (a test-harness
limitation, not a production issue).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from app.providers.bootstrap import transport_profile_id_for
from app.shared.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture()
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


class TestTransportProfileId:
    """HIGH-3: the transport identity is resolved from the registry, never a
    string guess — volcengine uses ark-*-v1, not volcengine-*-v1."""

    def test_volcengine_resolves_to_ark_transport(self) -> None:
        assert transport_profile_id_for("volcengine", "ark_cn_v1", "image") == "ark-image-v1"
        assert transport_profile_id_for("volcengine", "ark_cn_v1", "video") == "ark-video-v1"

    def test_agnes_resolves_to_agnes_transport(self) -> None:
        assert transport_profile_id_for("agnes", "agnes_cn_v1", "image") == "agnes-image-v1"
        assert transport_profile_id_for("agnes", "agnes_cn_v1", "video") == "agnes-video-v1"

    def test_unknown_combination_returns_none(self) -> None:
        assert transport_profile_id_for("volcengine", "ark_cn_v1", "voice") is None
