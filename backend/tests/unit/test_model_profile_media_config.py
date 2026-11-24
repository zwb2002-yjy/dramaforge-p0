"""D6 media configuration: CAS update, scope/kind validation and legacy reconcile (I8a-01)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.providers.model_profiles.errors import MODEL_PROFILE_VERSION_CONFLICT
from app.providers.model_profiles.models import ModelSlotBinding
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.model_profiles.slots import ModelSlot
from app.providers.models import ProviderModelBinding
from app.shared.errors import ValidationAppError
from model_infra_fixture import seed_model_infra
from model_profile_helpers import TEST_TEXT_A, build_test_registry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def world(session: AsyncSession):
    suffix = uuid4().hex[:8]
    user = User(email=f"media-{suffix}@example.com", display_name="M", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{suffix}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id, name=f"P-{suffix}", aspect_ratio="9:16", budget_limit=0
    )
    session.add(project)
    await session.flush()
    await seed_model_infra(session, project=project, user=user)
    return {"user": user, "workspace": workspace, "project": project}


@pytest.fixture
def registry():
    return build_test_registry()


@pytest.fixture
async def service(session: AsyncSession, registry):
    return ProductionModelProfileService(session, registry=registry)


async def _binding_id(session: AsyncSession, *, purpose: str) -> object:
    return await session.scalar(
        select(ProviderModelBinding.id).where(ProviderModelBinding.purpose == purpose)
    )


async def _project_profile(service, world):
    profile = await service.get_project_profile(project_id=world["project"].id)
    assert profile is not None
    return profile


async def test_media_config_cas_kind_and_scope(session, world, service):
    profile = await _project_profile(service, world)
    assert profile.media_config_version == 2
    image_id = await _binding_id(session, purpose="keyframe")
    video_id = await _binding_id(session, purpose="video")
    original_version = profile.version
    updated = await service.update_media_config(
        profile_id=profile.id,
        actor_id=world["user"].id,
        expected_version=original_version,
        image_model_binding_id=image_id,
        video_model_binding_id=video_id,
    )
    assert updated.version == original_version + 1
    config = await service.media_config(profile_id=profile.id)
    assert config.image_model_binding_id == image_id
    assert config.video_model_binding_id == video_id
    with pytest.raises(Exception) as stale:
        await service.update_media_config(
            profile_id=profile.id,
            actor_id=world["user"].id,
            expected_version=original_version,
        )
    assert stale.value.details["code"] == MODEL_PROFILE_VERSION_CONFLICT
    with pytest.raises(ValidationAppError) as kind:
        await service.update_media_config(
            profile_id=profile.id,
            actor_id=world["user"].id,
            expected_version=updated.version,
            video_model_binding_id=image_id,
        )
    assert kind.value.details["code"] == "MODEL_MEDIA_BINDING_KIND"
    with pytest.raises(ValidationAppError) as options:
        await service.update_media_config(
            profile_id=profile.id,
            actor_id=world["user"].id,
            expected_version=updated.version,
            voice_options={"voice_id": "v1"},
        )
    assert options.value.details["code"] == "MODEL_VOICE_OPTIONS_WITHOUT_BINDING"


async def test_workspace_profile_cannot_carry_media_defaults(session, world, service):
    workspace_profile = await service.create(
        workspace_id=world["workspace"].id,
        actor_id=world["user"].id,
        name="工作区默认",
        bindings={
            ModelSlot.PLANNING_SCRIPT: ModelSlotBinding(
                slot=ModelSlot.PLANNING_SCRIPT, model_id=TEST_TEXT_A
            )
        },
        is_default=True,
    )
    image_id = await _binding_id(session, purpose="keyframe")
    with pytest.raises(ValidationAppError) as scope:
        await service.update_media_config(
            profile_id=workspace_profile.id,
            actor_id=world["user"].id,
            expected_version=workspace_profile.version,
            image_model_binding_id=image_id,
        )
    assert scope.value.details["code"] == "MODEL_MEDIA_WORKSPACE_SCOPE"


async def test_legacy_version_is_reconciled_by_an_explicit_update(session, world, service):
    profile = await _project_profile(service, world)
    profile.media_config_version = 1
    await session.flush()
    image_id = await _binding_id(session, purpose="keyframe")
    updated = await service.update_media_config(
        profile_id=profile.id,
        actor_id=world["user"].id,
        expected_version=profile.version,
        image_model_binding_id=image_id,
    )
    assert updated.media_config_version == 2
    assert updated.image_model_binding_id == image_id


async def test_legacy_review_and_explicit_reconcile(session, world, service):
    profile = await _project_profile(service, world)
    profile.media_config_version = 1
    await session.flush()
    review = await service.media_config_review(profile_id=profile.id)
    assert review.media_config_version == 1
    slots = {conflict["slot"] for conflict in review.conflicts}
    assert "visual.keyframe" in slots
    image_id = await _binding_id(session, purpose="keyframe")
    with pytest.raises(ValidationAppError) as changed:
        await service.reconcile_media_config(
            profile_id=profile.id,
            actor_id=world["user"].id,
            expected_version=profile.version,
            review_fingerprint="0" * 64,
        )
    assert changed.value.details["code"] == "MODEL_MEDIA_REVIEW_CHANGED"
    original_version = profile.version
    updated = await service.reconcile_media_config(
        profile_id=profile.id,
        actor_id=world["user"].id,
        expected_version=original_version,
        review_fingerprint=review.review_fingerprint,
        image_model_binding_id=image_id,
    )
    assert updated.media_config_version == 2
    assert updated.image_model_binding_id == image_id
    assert not any(
        str(slot).startswith(("visual.", "video.")) for slot in updated.bindings
    )
    with pytest.raises(ValidationAppError) as done:
        await service.reconcile_media_config(
            profile_id=profile.id,
            actor_id=world["user"].id,
            expected_version=updated.version,
            review_fingerprint=review.review_fingerprint,
        )
    assert done.value.details["code"] == "MODEL_MEDIA_ALREADY_RECONCILED"
