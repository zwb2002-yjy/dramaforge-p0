"""Voice binding status projection: configured / unavailable / missing (I8a-02)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.model_profiles.service import ProductionModelProfileService
from app.providers.models import ProviderModelBinding
from app.providers.voice_binding import resolve_voice_binding
from model_infra_fixture import seed_model_infra
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def world(session: AsyncSession):
    suffix = uuid4().hex[:8]
    user = User(email=f"voice-{suffix}@example.com", display_name="V", password_hash="x")
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


async def _voice_binding(
    session: AsyncSession, world, *, enabled: bool = True
) -> ProviderModelBinding:
    connection_id = await session.scalar(
        select(ProviderModelBinding.connection_id).where(
            ProviderModelBinding.workspace_id == world["workspace"].id
        )
    )
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id=f"unit-voice-{uuid4().hex[:6]}",
        model_revision="1",
        display_name="Unit Voice",
        media_kind="voice",
        capability_manifest_json={"manifest_version": "1", "media_kind": "voice"},
        option_schema_json={},
        pricing_snapshot_json={},
        documented_at=date(2026, 11, 19),
        contract_manifest_hash="a" * 64,
    )
    session.add(entry)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=world["workspace"].id,
        connection_id=connection_id,
        media_type="voice",
        model_id=entry.model_id,
        purpose="voice",
        enabled=enabled,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        created_by=world["user"].id,
        updated_by=world["user"].id,
    )
    session.add(binding)
    await session.flush()
    return binding


async def _profile(session: AsyncSession, world):
    service = ProductionModelProfileService(session)
    profile = await service.get_project_profile(project_id=world["project"].id)
    assert profile is not None
    return profile


async def test_missing_voice_binding(session, world):
    status = await resolve_voice_binding(session, project=world["project"])
    assert status.status == "missing"
    assert status.reason_code == "VOICE_BINDING_MISSING"


async def test_configured_voice_binding_carries_options(session, world):
    binding = await _voice_binding(session, world)
    profile = await _profile(session, world)
    profile.voice_model_binding_id = binding.id
    profile.voice_options = {"voice_id": "v1", "speed": 1.0}
    await session.flush()
    status = await resolve_voice_binding(session, project=world["project"])
    assert status.status == "configured"
    assert status.binding_id == binding.id
    assert status.model_id == binding.model_id
    assert status.provider_type == "agnes"
    assert status.voice_options == {"voice_id": "v1", "speed": 1.0}


async def test_disabled_and_wrong_kind_bindings_are_unavailable(session, world):
    binding = await _voice_binding(session, world, enabled=False)
    profile = await _profile(session, world)
    profile.voice_model_binding_id = binding.id
    await session.flush()
    disabled = await resolve_voice_binding(session, project=world["project"])
    assert disabled.status == "unavailable"
    assert disabled.reason_code == "VOICE_BINDING_DISABLED"

    binding.enabled = True
    binding.media_type = "image"
    binding.purpose = "keyframe"
    await session.flush()
    wrong = await resolve_voice_binding(session, project=world["project"])
    assert wrong.status == "unavailable"
    assert wrong.reason_code == "VOICE_BINDING_KIND_MISMATCH"
