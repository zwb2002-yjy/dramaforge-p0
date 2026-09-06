"""ProductionModelProfile service tests (spec §116 M10: CRUD / validation /
simple mode / version conflict / snapshot)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.providers.model_profiles.errors import (
    MODEL_PROFILE_CAPABILITY_MISMATCH,
    MODEL_PROFILE_MODEL_NOT_FOUND,
    MODEL_PROFILE_NATIVE_OPTION_INVALID,
    MODEL_PROFILE_VERSION_CONFLICT,
)
from app.providers.model_profiles.models import ModelSlotBinding, SimpleModeSelection
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.service import (
    ProductionModelProfileService,
    parse_bindings,
)
from app.providers.model_profiles.slots import ModelSlot
from app.shared.base import Base
from model_profile_helpers import (
    TEST_IMAGE_A,
    TEST_TEXT_A,
    TEST_TEXT_B,
    TEST_VIDEO_I2V,
    build_test_registry,
)
from sqlalchemy import select
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
        email=f"profile-{suffix}@example.com",
        display_name="P",
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


@pytest.fixture
async def service(session: AsyncSession, registry):
    return ProductionModelProfileService(session, registry=registry)


def _binding(slot: ModelSlot, model_id: str, **kwargs) -> ModelSlotBinding:
    return ModelSlotBinding(slot=slot, model_id=model_id, **kwargs)


async def test_create_workspace_default_and_read(session: AsyncSession, world, service) -> None:
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="默认制作方案",
        bindings={
            ModelSlot.PLANNING_SCRIPT: _binding(ModelSlot.PLANNING_SCRIPT, TEST_TEXT_A),
            ModelSlot.VISUAL_KEYFRAME: _binding(ModelSlot.VISUAL_KEYFRAME, TEST_IMAGE_A),
        },
        is_default=True,
    )
    await session.flush()
    assert profile.version == 1
    assert profile.is_default is True
    default = await service.get_workspace_default(workspace_id=world["workspace"].id)
    assert default is not None and default.id == profile.id
    listed = await service.list_workspace_profiles(workspace_id=world["workspace"].id)
    assert len(listed) == 1


async def test_only_one_workspace_default(session: AsyncSession, world, service) -> None:
    actor = world["user"].id
    await service.create(
        workspace_id=world["workspace"].id,
        actor_id=actor,
        name="第一",
        bindings={},
        is_default=True,
    )
    await service.create(
        workspace_id=world["workspace"].id,
        actor_id=actor,
        name="第二",
        bindings={},
        is_default=True,
    )
    await session.flush()
    default = await service.get_workspace_default(workspace_id=world["workspace"].id)
    assert default is not None and default.name == "第二"


async def test_cannot_create_second_project_profile(session: AsyncSession, world, service) -> None:
    await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="项目方案",
        bindings={},
        project_id=world["project"].id,
    )
    with pytest.raises(Exception) as exc_info:
        await service.create(
            workspace_id=world["workspace"].id,
            actor_id=world["user"].id,
            name="另一个",
            bindings={},
            project_id=world["project"].id,
        )
    assert exc_info.value.details["code"] == "MODEL_PROFILE_EXISTS"


async def test_update_increments_version(session: AsyncSession, world, service) -> None:
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="方案",
        bindings={ModelSlot.PLANNING_SCRIPT: _binding(ModelSlot.PLANNING_SCRIPT, TEST_TEXT_A)},
        is_default=True,
    )
    await session.flush()
    updated = await service.update(
        profile_id=profile.id,
        actor_id=world["user"].id,
        bindings={ModelSlot.PLANNING_SCRIPT: _binding(ModelSlot.PLANNING_SCRIPT, TEST_TEXT_B)},
        expected_version=1,
    )
    await session.flush()
    assert updated.version == 2
    parsed = parse_bindings(updated.bindings)
    assert parsed[ModelSlot.PLANNING_SCRIPT].model_id == TEST_TEXT_B


async def test_update_version_conflict(session: AsyncSession, world, service) -> None:
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="方案",
        bindings={},
        is_default=True,
    )
    await session.flush()
    with pytest.raises(Exception) as exc_info:
        await service.update(
            profile_id=profile.id,
            actor_id=world["user"].id,
            name="改名",
            expected_version=99,
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_VERSION_CONFLICT


async def test_validation_rejects_unknown_model(session: AsyncSession, world, service) -> None:
    with pytest.raises(Exception) as exc_info:
        await service.create(
            workspace_id=world["workspace"].id,
            actor_id=world["user"].id,
            name="方案",
            bindings={
                ModelSlot.PLANNING_SCRIPT: _binding(ModelSlot.PLANNING_SCRIPT, "nope/missing")
            },
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_MODEL_NOT_FOUND


async def test_validation_rejects_capability_mismatch(
    session: AsyncSession, world, service
) -> None:
    with pytest.raises(Exception) as exc_info:
        await service.create(
            workspace_id=world["workspace"].id,
            actor_id=world["user"].id,
            name="方案",
            bindings={
                ModelSlot.PLANNING_SCRIPT: _binding(ModelSlot.PLANNING_SCRIPT, TEST_VIDEO_I2V)
            },
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_CAPABILITY_MISMATCH


async def test_validation_rejects_unknown_native_option(
    session: AsyncSession, world, service
) -> None:
    with pytest.raises(Exception) as exc_info:
        await service.create(
            workspace_id=world["workspace"].id,
            actor_id=world["user"].id,
            name="方案",
            bindings={
                ModelSlot.PLANNING_SCRIPT: _binding(
                    ModelSlot.PLANNING_SCRIPT, TEST_TEXT_A, native_options={"nope": 1}
                )
            },
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_NATIVE_OPTION_INVALID


async def test_simple_mode_maps_groups_to_slots(session: AsyncSession, world, service) -> None:
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="方案",
        bindings={},
        is_default=True,
    )
    await session.flush()
    updated = await service.apply_simple_mode(
        profile_id=profile.id,
        selection=SimpleModeSelection(
            llm_model_id=TEST_TEXT_A,
            image_model_id=TEST_IMAGE_A,
            video_model_id=TEST_VIDEO_I2V,
        ),
        actor_id=world["user"].id,
        expected_version=1,
    )
    await session.flush()
    parsed = parse_bindings(updated.bindings)
    assert parsed[ModelSlot.PLANNING_BRIEF].model_id == TEST_TEXT_A
    assert parsed[ModelSlot.PLANNING_SCRIPT].model_id == TEST_TEXT_A
    assert parsed[ModelSlot.PLANNING_STORYBOARD].model_id == TEST_TEXT_A
    assert parsed[ModelSlot.VISUAL_CHARACTER].model_id == TEST_IMAGE_A
    assert parsed[ModelSlot.VISUAL_STORYBOARD].model_id == TEST_IMAGE_A
    assert parsed[ModelSlot.VISUAL_KEYFRAME].model_id == TEST_IMAGE_A
    assert parsed[ModelSlot.VIDEO_SHOT].model_id == TEST_VIDEO_I2V


async def test_copy_from_snapshots_workspace_default(session: AsyncSession, world, service) -> None:
    workspace_default = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="默认",
        bindings={ModelSlot.PLANNING_SCRIPT: _binding(ModelSlot.PLANNING_SCRIPT, TEST_TEXT_A)},
        is_default=True,
    )
    await session.flush()
    project_profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="项目方案",
        bindings={},
        project_id=world["project"].id,
        copy_from=workspace_default.id,
    )
    await session.flush()
    assert project_profile.version == 1
    parsed = parse_bindings(project_profile.bindings)
    assert parsed[ModelSlot.PLANNING_SCRIPT].model_id == TEST_TEXT_A


async def test_snapshot_for_project_freezes_bindings(session: AsyncSession, world, service) -> None:
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="默认",
        bindings={ModelSlot.PLANNING_SCRIPT: _binding(ModelSlot.PLANNING_SCRIPT, TEST_TEXT_A)},
        is_default=True,
    )
    await session.flush()
    snapshot = await service.snapshot_for_project(project=world["project"])
    assert snapshot.profile_id == profile.id
    assert snapshot.profile_version == 1
    binding = snapshot.bindings[ModelSlot.PLANNING_SCRIPT]
    assert binding.model_id == TEST_TEXT_A
    assert binding.source == "workspace_profile"
    assert binding.capability.value == "text.generate"


async def test_delete_non_default_workspace_profile(session: AsyncSession, world, service) -> None:
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="非默认",
        bindings={},
        is_default=False,
    )
    await session.flush()
    await service.delete(profile_id=profile.id, actor_id=world["user"].id)
    await session.flush()
    rows = (
        (
            await session.execute(
                select(ProductionModelProfile).where(ProductionModelProfile.id == profile.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


async def test_cannot_delete_workspace_default(session: AsyncSession, world, service) -> None:
    profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="默认",
        bindings={},
        is_default=True,
    )
    await session.flush()
    with pytest.raises(Exception) as exc_info:
        await service.delete(profile_id=profile.id, actor_id=world["user"].id)
    assert exc_info.value.details["code"] == "MODEL_PROFILE_DEFAULT_PROTECTED"
