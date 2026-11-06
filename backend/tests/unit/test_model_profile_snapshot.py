"""Model-profile snapshot + M9 slot-integration tests (spec §22, §43, §92)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.providers.capabilities import Capability
from app.providers.model_profiles.models import ModelSlotBinding
from app.providers.model_profiles.node_snapshot import (
    derive_video_capability,
    planned_node_model_profile,
)
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.model_profiles.slots import ModelSlot
from app.shared.base import Base
from model_profile_helpers import (
    TEST_IMAGE_A,
    TEST_TEXT_A,
    build_test_registry,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def world(session: AsyncSession):
    suffix = uuid4().hex[:8]
    user = User(
        email=f"snap-{suffix}@example.com",
        display_name="S",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{suffix}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{suffix}",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()
    return {"user": user, "workspace": workspace, "project": project}


@pytest.fixture
def registry():
    return build_test_registry()


def test_derive_video_capability_order() -> None:
    assert (
        derive_video_capability(first_frame=True, last_frame=True, references=True)
        is Capability.VIDEO_FIRST_LAST_FRAME
    )
    assert (
        derive_video_capability(first_frame=True, last_frame=False, references=False)
        is Capability.VIDEO_IMAGE_TO_VIDEO
    )
    assert (
        derive_video_capability(first_frame=False, last_frame=False, references=True)
        is Capability.VIDEO_REFERENCE_TO_VIDEO
    )
    assert (
        derive_video_capability(first_frame=False, last_frame=False, references=False)
        is Capability.VIDEO_TEXT_TO_VIDEO
    )
    # first beats references (spec §43 order)
    assert (
        derive_video_capability(first_frame=True, last_frame=False, references=True)
        is Capability.VIDEO_IMAGE_TO_VIDEO
    )


async def test_planned_node_profile_records_slot_and_profile_version(
    session: AsyncSession, world, registry
) -> None:
    service = ProductionModelProfileService(session, registry=registry)
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="方案",
        bindings={
            ModelSlot.VISUAL_KEYFRAME: ModelSlotBinding(
                slot=ModelSlot.VISUAL_KEYFRAME, model_id=TEST_IMAGE_A
            )
        },
        is_default=True,
    )
    await session.flush()
    profile_mp = await planned_node_model_profile(
        session, project=world["project"], node_key="keyframe", registry=registry
    )
    assert profile_mp["slot"] == "visual.keyframe"
    assert profile_mp["model_id"] == TEST_IMAGE_A
    assert profile_mp["source"] == "workspace_profile"
    assert profile_mp["profile_id"] == str(profile.id)
    assert profile_mp["profile_version"] == 1


async def test_planned_node_profile_never_raises_without_models(
    session: AsyncSession, world
) -> None:
    """A project with no profile still resolves a planned snapshot (system
    default or a no-model marker) without blocking materialization."""
    mp = await planned_node_model_profile(session, project=world["project"], node_key="keyframe")
    assert mp["slot"] == "visual.keyframe"
    # Either a system default resolved or an explicit no-model marker.
    assert mp.get("model_id") is not None or mp.get("error") is not None
    # Unknown node key → empty (no slot concept).
    assert (
        await planned_node_model_profile(session, project=world["project"], node_key="composite")
        == {}
    )


async def test_text_slot_snapshots_round_trip(session: AsyncSession, world, registry) -> None:
    service = ProductionModelProfileService(session, registry=registry)
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="方案",
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT, model_id=TEST_TEXT_A
            )
        },
        is_default=True,
    )
    await session.flush()
    snapshot = await service.snapshot_for_project(project=world["project"])
    assert snapshot.profile_id == profile.id
    binding = snapshot.bindings[ModelSlot.PLANNING_SCRIPT]
    assert binding.model_id == TEST_TEXT_A
