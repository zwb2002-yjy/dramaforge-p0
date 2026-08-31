"""MS1-R/MS1-C tests for the one Professional execution resolver."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolver
from app.providers.models import ProjectProviderBinding, ProviderConnection, ProviderModelBinding
from app.security.models import EncryptedProviderCredential
from app.shared.base import Base
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


async def _seed(session: AsyncSession) -> tuple[Project, ProviderModelBinding, User]:
    user = User(
        email=f"resolution-{uuid4().hex}@example.com",
        display_name="Resolution",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
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
    credential = EncryptedProviderCredential(
        workspace_id=workspace.id,
        provider="agnes",
        revision_no=1,
        ciphertext="test-ciphertext",
        key_version="test-v1",
    )
    session.add(credential)
    await session.flush()
    manifest = next(item for item in SEED_MANIFESTS if item["model_id"] == "agnes-video-v2.0")
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
        credential_id=credential.id,
        credential_revision=credential.revision_no,
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
        account_verified=True,
        quality_gated=True,
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
    return project, binding, user


def _bindings(slot: ModelSlot, model_id: str) -> dict[str, object]:
    return {
        slot.value: {
            "slot": slot.value,
            "model_id": model_id,
            "native_options": {"seed": 7},
            "enabled": True,
        }
    }


async def _resolve(session: AsyncSession, project: Project, **kwargs: object):
    return await ExecutionModelResolver(session).resolve(
        project=project,
        slot=ModelSlot.VIDEO_SHOT,
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        purpose="video",
        mode_id="explicit_binding",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_explicit_binding_freezes_concrete_identity(session: AsyncSession) -> None:
    project, binding, _user = await _seed(session)
    result = await _resolve(session, project, requested_binding_id=binding.id)
    assert result.status == "RESOLVED"
    assert result.source == "request_override"
    assert result.provider_model_binding_id == binding.id
    assert result.resolved_model_id == "agnes/agnes-video-v2.0"
    assert result.manifest_hash == binding.capability_manifest_hash
    assert result.credential_revision_id is None


@pytest.mark.asyncio
async def test_project_slot_beats_workspace_slot(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    session.add_all(
        [
            ProductionModelProfile(
                workspace_id=project.workspace_id,
                project_id=None,
                name="workspace",
                version=1,
                is_default=True,
                bindings=_bindings(ModelSlot.VIDEO_SHOT, "missing/video"),
                created_by=user.id,
                updated_by=user.id,
            ),
            ProductionModelProfile(
                workspace_id=project.workspace_id,
                project_id=project.id,
                name="project",
                version=1,
                is_default=False,
                bindings=_bindings(ModelSlot.VIDEO_SHOT, "agnes/agnes-video-v2.0"),
                created_by=user.id,
                updated_by=user.id,
            ),
        ]
    )
    await session.flush()
    result = await _resolve(session, project)
    assert result.status == "RESOLVED"
    assert result.source == "project_profile"
    assert result.provider_model_binding_id == binding.id


@pytest.mark.asyncio
async def test_project_slot_absent_inherits_workspace_slot(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    session.add_all(
        [
            ProductionModelProfile(
                workspace_id=project.workspace_id,
                project_id=None,
                name="workspace",
                version=1,
                is_default=True,
                bindings=_bindings(ModelSlot.VIDEO_SHOT, "agnes/agnes-video-v2.0"),
                created_by=user.id,
                updated_by=user.id,
            ),
            ProductionModelProfile(
                workspace_id=project.workspace_id,
                project_id=project.id,
                name="project",
                version=1,
                is_default=False,
                bindings=_bindings(ModelSlot.VISUAL_KEYFRAME, "missing/image"),
                created_by=user.id,
                updated_by=user.id,
            ),
        ]
    )
    await session.flush()
    result = await _resolve(session, project)
    assert result.status == "RESOLVED"
    assert result.source == "workspace_profile"
    assert result.provider_model_binding_id == binding.id


@pytest.mark.asyncio
async def test_no_profile_uses_legacy_binding_only_as_system_default(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=user.id,
        )
    )
    await session.flush()
    result = await _resolve(session, project)
    assert result.status == "RESOLVED"
    assert result.source == "system_default"
    assert result.provider_model_binding_id == binding.id


@pytest.mark.asyncio
async def test_unavailable_profile_model_does_not_run_legacy_binding(session: AsyncSession) -> None:
    project, binding, user = await _seed(session)
    session.add_all(
        [
            ProductionModelProfile(
                workspace_id=project.workspace_id,
                project_id=None,
                name="workspace",
                version=1,
                is_default=True,
                bindings=_bindings(ModelSlot.VIDEO_SHOT, "missing/video"),
                created_by=user.id,
                updated_by=user.id,
            ),
            ProjectProviderBinding(
                project_id=project.id,
                workspace_id=project.workspace_id,
                purpose="video",
                model_binding_id=binding.id,
                selection_strategy="explicit_binding",
                fallback_policy="none",
                updated_by=user.id,
            ),
        ]
    )
    await session.flush()
    result = await _resolve(session, project)
    assert result.status == "UNAVAILABLE"
    assert result.source == "workspace_profile"
    assert result.reason == "MODEL_BINDING_UNAVAILABLE"
    assert result.provider_model_binding_id is None
