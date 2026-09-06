"""ModelBindingResolver tests (spec §120–§122, M3)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.providers.capabilities import Capability
from app.providers.errors import UnsupportedCapabilityError
from app.providers.model_profiles.errors import (
    MODEL_PROFILE_CAPABILITY_MISMATCH,
    MODEL_PROFILE_NO_AVAILABLE_MODEL,
)
from app.providers.model_profiles.models import ModelSlotBinding
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.resolver import ModelBindingResolver
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.model_profiles.slots import ModelSlot
from app.shared.base import Base
from model_profile_helpers import (
    TEST_TEXT_A,
    TEST_TEXT_B,
    TEST_VIDEO_FULL,
    TEST_VIDEO_I2V,
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
        email=f"resolver-{suffix}@example.com",
        display_name="R",
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


async def _make_workspace_default(
    service: ProductionModelProfileService,
    session: AsyncSession,
    *,
    workspace_id,
    actor_id,
    bindings: dict[ModelSlot, ModelSlotBinding],
) -> ProductionModelProfile:
    return await service.create(
        workspace_id=workspace_id,
        actor_id=actor_id,
        name="默认方案",
        bindings=bindings,
        is_default=True,
    )


async def test_request_override_beats_project_and_workspace(
    session: AsyncSession, world, service
) -> None:
    workspace = world["workspace"]
    project = world["project"]
    await _make_workspace_default(
        service,
        session,
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT, model_id=TEST_TEXT_A
            )
        },
    )
    resolver = ModelBindingResolver(session, registry=service._registry)
    resolved = await resolver.resolve(
        workspace_id=workspace.id,
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
        capability=Capability.TEXT_GENERATE,
        requested_model_id=TEST_TEXT_B,
    )
    assert resolved.model_id == TEST_TEXT_B
    assert resolved.source == "request_override"
    assert resolved.profile_id is None


async def test_project_profile_beats_workspace(session: AsyncSession, world, service) -> None:
    workspace = world["workspace"]
    project = world["project"]
    await _make_workspace_default(
        service,
        session,
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT, model_id=TEST_TEXT_A
            )
        },
    )
    project_profile = await service.create(
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        name="项目方案",
        project_id=project.id,
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT, model_id=TEST_TEXT_B
            )
        },
    )
    resolver = ModelBindingResolver(session, registry=service._registry)
    resolved = await resolver.resolve(
        workspace_id=workspace.id,
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
        capability=Capability.TEXT_GENERATE,
    )
    assert resolved.model_id == TEST_TEXT_B
    assert resolved.source == "project_profile"
    assert resolved.profile_id == project_profile.id
    assert resolved.profile_version == 1


async def test_workspace_default_beats_system(session: AsyncSession, world, service) -> None:
    workspace = world["workspace"]
    project = world["project"]
    profile = await _make_workspace_default(
        service,
        session,
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT, model_id=TEST_TEXT_A
            )
        },
    )
    resolver = ModelBindingResolver(session, registry=service._registry)
    resolved = await resolver.resolve(
        workspace_id=workspace.id,
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
        capability=Capability.TEXT_GENERATE,
    )
    assert resolved.model_id == TEST_TEXT_A
    assert resolved.source == "workspace_profile"
    assert resolved.profile_id == profile.id


async def test_system_default_fallback(session: AsyncSession, world, service) -> None:
    workspace = world["workspace"]
    project = world["project"]
    resolver = ModelBindingResolver(session, registry=service._registry)
    resolved = await resolver.resolve(
        workspace_id=workspace.id,
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
        capability=Capability.TEXT_GENERATE,
    )
    assert resolved.source == "system_default"
    assert resolved.model_id in {TEST_TEXT_A, TEST_TEXT_B}


async def test_missing_all_models_raises_no_available(
    session: AsyncSession, world, service
) -> None:
    workspace = world["workspace"]
    project = world["project"]
    resolver = ModelBindingResolver(session, registry=service._registry)
    with pytest.raises(Exception) as exc_info:
        await resolver.resolve(
            workspace_id=workspace.id,
            project_id=project.id,
            slot=ModelSlot.AUDIO_TTS,
            capability=Capability.AUDIO_TTS,
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_NO_AVAILABLE_MODEL


async def test_video_derived_capability_mismatch_fails_fast(
    session: AsyncSession, world, service
) -> None:
    """spec §122: video.shot bound to an i2v-only model; a first+last frame
    request must be rejected before any provider call."""
    workspace = world["workspace"]
    project = world["project"]
    await _make_workspace_default(
        service,
        session,
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        bindings={
            ModelSlot.VIDEO_SHOT: ModelSlotBinding(
                slot=ModelSlot.VIDEO_SHOT, model_id=TEST_VIDEO_I2V
            )
        },
    )
    resolver = ModelBindingResolver(session, registry=service._registry)
    # i2v request is fine
    ok = await resolver.resolve(
        workspace_id=workspace.id,
        project_id=project.id,
        slot=ModelSlot.VIDEO_SHOT,
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
    )
    assert ok.model_id == TEST_VIDEO_I2V
    # first_last_frame is not supported -> fail fast, no silent switch
    with pytest.raises(Exception) as exc_info:
        await resolver.resolve(
            workspace_id=workspace.id,
            project_id=project.id,
            slot=ModelSlot.VIDEO_SHOT,
            capability=Capability.VIDEO_FIRST_LAST_FRAME,
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_CAPABILITY_MISMATCH


async def test_full_video_model_serves_all_video_capabilities(
    session: AsyncSession, world, service
) -> None:
    workspace = world["workspace"]
    project = world["project"]
    await _make_workspace_default(
        service,
        session,
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        bindings={
            ModelSlot.VIDEO_SHOT: ModelSlotBinding(
                slot=ModelSlot.VIDEO_SHOT, model_id=TEST_VIDEO_FULL
            )
        },
    )
    resolver = ModelBindingResolver(session, registry=service._registry)
    for capability in (
        Capability.VIDEO_TEXT_TO_VIDEO,
        Capability.VIDEO_IMAGE_TO_VIDEO,
        Capability.VIDEO_FIRST_LAST_FRAME,
        Capability.VIDEO_REFERENCE_TO_VIDEO,
    ):
        resolved = await resolver.resolve(
            workspace_id=workspace.id,
            project_id=project.id,
            slot=ModelSlot.VIDEO_SHOT,
            capability=capability,
        )
        assert resolved.model_id == TEST_VIDEO_FULL


async def test_unknown_requested_model_raises(session: AsyncSession, world, service) -> None:
    workspace = world["workspace"]
    project = world["project"]
    resolver = ModelBindingResolver(session, registry=service._registry)
    from app.providers.model_profiles.errors import MODEL_PROFILE_MODEL_NOT_FOUND

    with pytest.raises(Exception) as exc_info:
        await resolver.resolve(
            workspace_id=workspace.id,
            project_id=project.id,
            slot=ModelSlot.PLANNING_SCRIPT,
            capability=Capability.TEXT_GENERATE,
            requested_model_id="nope/missing",
        )
    assert exc_info.value.details["code"] == MODEL_PROFILE_MODEL_NOT_FOUND


async def test_request_override_with_wrong_capability_raises(
    session: AsyncSession, world, service
) -> None:
    workspace = world["workspace"]
    project = world["project"]
    resolver = ModelBindingResolver(session, registry=service._registry)
    with pytest.raises(UnsupportedCapabilityError):
        await resolver.resolve(
            workspace_id=workspace.id,
            project_id=project.id,
            slot=ModelSlot.PLANNING_SCRIPT,
            capability=Capability.IMAGE_GENERATE,
            requested_model_id=TEST_TEXT_A,
        )


async def test_disabled_binding_falls_through(session: AsyncSession, world, service) -> None:
    workspace = world["workspace"]
    project = world["project"]
    await _make_workspace_default(
        service,
        session,
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT, model_id=TEST_TEXT_A, enabled=False
            )
        },
    )
    resolver = ModelBindingResolver(session, registry=service._registry)
    resolved = await resolver.resolve(
        workspace_id=workspace.id,
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
        capability=Capability.TEXT_GENERATE,
    )
    assert resolved.source == "system_default"


async def test_native_options_carried_into_resolved_binding(
    session: AsyncSession, world, service
) -> None:
    workspace = world["workspace"]
    project = world["project"]
    await _make_workspace_default(
        service,
        session,
        workspace_id=workspace.id,
        actor_id=world["user"].id,
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT,
                model_id=TEST_TEXT_A,
                native_options={"temperature": 0.3},
            )
        },
    )
    resolver = ModelBindingResolver(session, registry=service._registry)
    resolved = await resolver.resolve(
        workspace_id=workspace.id,
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
        capability=Capability.TEXT_GENERATE,
    )
    assert resolved.native_options == {"temperature": 0.3}
