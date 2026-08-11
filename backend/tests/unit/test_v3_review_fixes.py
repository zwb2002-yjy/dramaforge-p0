"""V3 review-gate fixes (1.md): BLOCK-1 race recovery, HIGH-3 transport id,
HIGH-4 manifest selection.

The BLOCK-1 concurrent-race test runs at the service level in a single event
loop — the API TestClient reuses a StaticPool connection across per-request
event loops, which a rollback-then-query cannot survive (a test-harness
limitation, not a production issue).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.providers.bootstrap import transport_profile_id_for
from app.providers.capabilities import Capability
from app.providers.catalog_seed_data import seed_manifests_for
from app.providers.generation_service import GenerationService
from app.providers.router import CapabilityRouter
from app.providers.workspace_router import select_seed_manifest
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
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


class TestConcurrentIdempotencyRace:
    """BLOCK-1: two requests racing on the same key — the loser recovers from
    IntegrityError and returns the winner's operation instead of a 500."""

    async def test_race_recovery_returns_winner(self, tmp_path) -> None:
        """The UNIQUE-constraint race: when the insert conflicts, the service
        catches IntegrityError, rolls back, re-selects the winner and returns it
        instead of a 500. (The IntegrityError is raised in-process to exercise
        the recovery control flow — the aiosqlite driver masks the DB-level
        IntegrityError with a nested-greenlet quirk, which asyncpg in production
        does not.)"""
        import app.providers.generation_service as gen_mod
        from app.access.models import Project
        from app.providers.bootstrap import default_v3_registry
        from app.shared.base import Base
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_path = tmp_path / "race.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        router = CapabilityRouter(registry=default_v3_registry()[0])

        # Session A seeds the project chain and creates + commits the winner.
        async with factory() as session_a:
            user = User(
                email=f"race-{uuid4().hex}@example.com",
                display_name="Race",
                password_hash=hash_password("x"),
            )
            session_a.add(user)
            await session_a.flush()
            workspace = Workspace(owner_user_id=user.id, name="Race-ws")
            session_a.add(workspace)
            await session_a.flush()
            project = await ProjectService(session_a).create_project(
                workspace_id=workspace.id, name="Race-project", aspect_ratio="9:16", actor=user
            )
            await session_a.flush()
            user_id = user.id
            project_id = project.id
            service = GenerationService(session_a, router)
            winner = await service.create_generation(
                project=project,
                actor=user,
                capability=Capability.IMAGE_GENERATE,
                model_id=None,
                input_data={"prompt": "同一请求"},
                options={},
                native_options={},
                idempotency_key="K",
            )
            await session_a.commit()
            winner_id = winner.id

        # Session B races: pre-check misses, the insert conflicts (IntegrityError
        # raised in-process), and the recovery re-selects the committed winner.
        async with factory() as session_b:
            user_b = await session_b.get(User, user_id)
            project_b = await session_b.get(Project, project_id)
            assert user_b is not None and project_b is not None

            async def miss(*, project_id: object, idempotency_key: str) -> None:
                return None

            async def conflict(*args: object, **kwargs: object) -> object:
                raise IntegrityError("stmt", {}, Exception("race conflict"))

            original_create_run = gen_mod._create_generation_run
            service_b = GenerationService(session_b, router)
            service_b._existing_by_key = miss  # type: ignore[method-assign]
            gen_mod._create_generation_run = conflict  # type: ignore[assignment]
            try:
                recovered = await service_b.create_generation(
                    project=project_b,
                    actor=user_b,
                    capability=Capability.IMAGE_GENERATE,
                    model_id=None,
                    input_data={"prompt": "同一请求"},
                    options={},
                    native_options={},
                    idempotency_key="K",
                )
            finally:
                gen_mod._create_generation_run = original_create_run

        await engine.dispose()
        assert recovered.id == winner_id


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


class TestSeedManifestSelection:
    """HIGH-4: model selection is by media_kind, never by array position."""

    def test_picks_video_manifest_regardless_of_order(self) -> None:
        # Agnes seeds are ordered [image, video]; reversed proves selection is
        # by media_kind, not index.
        manifests = list(reversed(seed_manifests_for(provider_type="agnes")))
        manifest = select_seed_manifest(manifests, media_kind="video")
        assert manifest.model_id == "agnes-video-v2.0"

    def test_picks_image_manifest_by_kind(self) -> None:
        manifests = list(reversed(seed_manifests_for(provider_type="volcengine")))
        manifest = select_seed_manifest(manifests, media_kind="image")
        assert manifest.model_id == "doubao-seedream-4-0-250828"

    def test_missing_media_kind_raises(self) -> None:
        manifests = seed_manifests_for(provider_type="agnes")
        with pytest.raises(ValidationAppError):
            select_seed_manifest(manifests, media_kind="voice")
