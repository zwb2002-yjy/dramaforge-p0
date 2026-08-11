"""ModelSelectionService tests: explicit binding resolution, fail-closed."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.intents import (
    ArtifactReferenceIntent,
    ModelSelectionIntent,
    VideoGenerationIntentV1,
)
from app.providers.models import (
    ProjectProviderBinding,
    ProviderConnection,
    ProviderModelBinding,
)
from app.providers.selection import ModelSelectionService
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(
    session: AsyncSession,
    *,
    account_verified: bool = True,
    quality_gated: bool = True,
) -> tuple[Project, ProviderModelBinding]:
    user = User(
        email=f"sel-{uuid4().hex}@example.com",
        display_name="Sel",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Sel-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()

    manifest = next(m for m in SEED_MANIFESTS if m["model_id"] == "agnes-video-v2.0")
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
        model_revision="v1",
        display_name="Agnes Video",
        media_kind="video",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(manifest),
    )
    session.add(entry)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="video",
        model_id="agnes-video-v2.0",
        purpose="video",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=account_verified,
        quality_gated=quality_gated,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-video-v2.0",
        invoke_model_value="agnes-video-v2.0",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    return project, binding


def _intent(**over: object) -> VideoGenerationIntentV1:
    defaults: dict[str, object] = {
        "prompt": "p",
        "selection": ModelSelectionIntent(mode="explicit_binding"),
    }
    defaults.update(over)
    return VideoGenerationIntentV1(**defaults)


@pytest.mark.asyncio
async def test_explicit_project_binding_resolves_plan(session: AsyncSession) -> None:
    project, binding = await _seed(session)
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=uuid4(),
        )
    )
    await session.flush()
    plan = await ModelSelectionService(session).select_video(
        project=project, intent=_intent()
    )
    assert plan.model_binding_id == binding.id
    assert plan.invoke_model_value == "agnes-video-v2.0"
    assert plan.protocol_profile == "agnes_cn_v1"
    assert plan.purpose == "video"
    assert plan.evidence["account_verified"] is True


@pytest.mark.asyncio
async def test_missing_project_binding_is_fail_closed(session: AsyncSession) -> None:
    project, _binding = await _seed(session)
    with pytest.raises(ValidationAppError) as exc_info:
        await ModelSelectionService(session).select_video(project=project, intent=_intent())
    assert exc_info.value.details["code"] == "MODEL_BINDING_MISSING"


@pytest.mark.asyncio
async def test_profile_binding_drives_media_selection_without_project_binding(
    session: AsyncSession,
) -> None:
    """M9/M1-fix: a workspace-default model profile binding video.shot to the
    seeded agnes model resolves the A+B selection even without a
    ProjectProviderBinding (spec §134 rule 6 — profile is the driver)."""
    project, binding = await _seed(session)
    from app.providers.model_profiles.models import ModelSlotBinding
    from app.providers.model_profiles.service import ProductionModelProfileService
    from app.providers.model_profiles.slots import ModelSlot

    service = ProductionModelProfileService(session)
    await service.create(
        workspace_id=project.workspace_id,
        actor_id=binding.created_by,
        name="默认方案",
        bindings={
            ModelSlot.VIDEO_SHOT: ModelSlotBinding(
                slot=ModelSlot.VIDEO_SHOT,
                model_id="agnes/agnes-video-v2.0",
            )
        },
        is_default=True,
    )
    await session.flush()
    plan = await ModelSelectionService(session).select_video(
        project=project, intent=_intent()
    )
    assert plan.model_binding_id == binding.id
    assert plan.invoke_model_value == "agnes-video-v2.0"
    assert plan.protocol_profile == "agnes_cn_v1"


@pytest.mark.asyncio
async def test_profile_binding_without_credential_falls_back_to_project_binding(
    session: AsyncSession,
) -> None:
    """A profile model with no matching credentialed ProviderModelBinding falls
    back to the project binding (fix for finding #1)."""
    project, binding = await _seed(session)
    from app.providers.model_profiles.models import ModelSlotBinding
    from app.providers.model_profiles.service import ProductionModelProfileService
    from app.providers.model_profiles.slots import ModelSlot
    from app.providers.models import ProjectProviderBinding

    service = ProductionModelProfileService(session)
    await service.create(
        workspace_id=project.workspace_id,
        actor_id=binding.created_by,
        name="默认方案",
        bindings={
            ModelSlot.VIDEO_SHOT: ModelSlotBinding(
                slot=ModelSlot.VIDEO_SHOT,
                # A registered model with no credentialed binding in this
                # workspace (only agnes is connected) → fall back.
                model_id="volcengine/doubao-seedance-1-0-pro-250528",
            )
        },
        is_default=True,
    )
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=uuid4(),
        )
    )
    await session.flush()
    plan = await ModelSelectionService(session).select_video(
        project=project, intent=_intent()
    )
    assert plan.model_binding_id == binding.id
    assert plan.invoke_model_value == "agnes-video-v2.0"


@pytest.mark.asyncio
async def test_unverified_binding_is_fail_closed(session: AsyncSession) -> None:
    project, binding = await _seed(session, account_verified=False, quality_gated=False)
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=uuid4(),
        )
    )
    await session.flush()
    with pytest.raises(ValidationAppError) as exc_info:
        await ModelSelectionService(session).select_video(project=project, intent=_intent())
    issues = exc_info.value.details["issues"]
    assert "MODEL_NOT_ACCOUNT_VERIFIED" in issues
    assert "MODEL_QUALITY_GATE_MISSING" in issues


@pytest.mark.asyncio
async def test_unsatisfiable_required_capability_is_fail_closed(
    session: AsyncSession,
) -> None:
    project, binding = await _seed(session)
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=uuid4(),
        )
    )
    await session.flush()
    intent = _intent(requirements={"required_capabilities": {"video.i2v.last_frame"}})
    with pytest.raises(ValidationAppError) as exc_info:
        await ModelSelectionService(session).select_video(project=project, intent=intent)
    assert "CAPABILITY_REQUIRED_MISSING" in exc_info.value.details["issues"]


@pytest.mark.asyncio
async def test_real_video_model_with_first_frame_is_selectable(
    session: AsyncSession,
) -> None:
    """Review gate 1: the real Agnes video manifest declares
    ``video.i2v.first_frame``; a video intent that carries a first_frame
    reference must resolve (not MODEL_INELIGIBLE)."""
    project, binding = await _seed(session)
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=uuid4(),
        )
    )
    await session.flush()
    intent = VideoGenerationIntentV1(
        prompt="p",
        references=[
            ArtifactReferenceIntent(artifact_id=uuid4(), role="first_frame", required=True)
        ],
        selection=ModelSelectionIntent(mode="explicit_binding"),
    )
    plan = await ModelSelectionService(session).select_video(project=project, intent=intent)
    assert plan.invoke_model_value == "agnes-video-v2.0"
    assert "video.i2v.first_frame" in plan.supported_capabilities
    assert plan.unmet_requirements == []
