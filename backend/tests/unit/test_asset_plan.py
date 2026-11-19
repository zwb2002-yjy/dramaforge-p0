"""Asset image execution plan: read-only, binding-bound, no fake shot (I8a-03)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, ProjectCreativeProfile, User, Workspace
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.production.asset_plan import (
    AssetCreativeRequirements,
    AssetImagePlanBody,
    build_asset_image_plan,
)
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.security.models import EncryptedProviderCredential
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _manifest(*, with_reference: bool = False) -> dict:
    operation: dict = {
        "operation": "image.generate",
        "capabilities": ["image.t2i"],
        "output_options": {
            "aspect_ratio": {
                "type": "string",
                "default": "1:1",
                "enum": ["1:1", "9:16"],
            }
        },
        "output_constraints": {"max_outputs": 2},
    }
    if with_reference:
        operation["reference_constraints"] = {"reference_image": {"min": 0, "max": 1}}
    return {
        "manifest_version": "1",
        "provider_type": "agnes",
        "protocol_profile": "agnes_cn_v1",
        "model_id": "asset-image",
        "model_revision": "v1",
        "media_kind": "image",
        "display_name": "Asset Image",
        "documented_at": date(2026, 8, 10).isoformat(),
        "operations": {"image.generate": operation},
        "option_schema": {"namespace": ""},
    }


@pytest.fixture
async def world(session: AsyncSession):
    suffix = uuid4().hex[:8]
    user = User(email=f"asset-{suffix}@example.com", display_name="A", password_hash="x")
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
    session.add(
        ProjectCreativeProfile(
            project_id=project.id, start_type="FREE", director_autonomy="MANUAL"
        )
    )
    credential = EncryptedProviderCredential(
        workspace_id=workspace.id,
        provider="agnes",
        revision_no=1,
        ciphertext="fixture-not-a-real-ciphertext",
        key_version="fixture",
    )
    session.add(credential)
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
    from app.providers.models import ProviderConnectionRevision

    session.add(
        ProviderConnectionRevision(
            connection_id=connection.id,
            revision_no=1,
            provider_type="agnes",
            protocol_profile="agnes_cn_v1",
            base_url="https://api.agnes-ai.cn",
            credential_revision_id=credential.id,
        )
    )
    await session.flush()
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="asset-image",
        model_revision="v1",
        display_name="Asset Image",
        media_kind="image",
        capability_manifest_json=_manifest(with_reference=True),
        option_schema_json={},
        documented_at=date(2026, 8, 10),
        contract_manifest_hash="b" * 64,
    )
    session.add(entry)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="image",
        model_id="asset-image",
        purpose="keyframe",
        enabled=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    profile = ProductionModelProfile(
        workspace_id=workspace.id,
        project_id=project.id,
        name="default",
        version=1,
        bindings={},
        image_model_binding_id=binding.id,
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(profile)
    voice_entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="openai_speech_v1",
        model_id="asset-voice",
        model_revision="v1",
        display_name="Asset Voice",
        media_kind="voice",
        capability_manifest_json={"manifest_version": "1", "media_kind": "voice"},
        option_schema_json={
            "voices": [{"id": "v1", "label": "Voice", "locale": "zh-CN"}],
            "properties": {"voice_id": {}},
        },
        documented_at=date(2026, 8, 10),
        contract_manifest_hash="d" * 64,
    )
    session.add(voice_entry)
    await session.flush()
    voice_binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="voice",
        model_id="asset-voice",
        purpose="voice",
        enabled=True,
        catalog_entry_id=voice_entry.id,
        capability_manifest_hash=voice_entry.contract_manifest_hash,
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(voice_binding)
    await session.flush()
    profile.voice_model_binding_id = voice_binding.id
    profile.voice_options = {"voice_id": "v1"}
    await session.flush()
    audio = Asset(project_id=project.id, kind="audio", name="Narration", version=1)
    session.add(audio)
    await session.flush()
    audio_version = AssetVersion(
        project_id=project.id,
        asset_id=audio.id,
        version_number=1,
        kind="audio",
        name="Narration",
        description="",
        metadata_json={},
        status="candidate",
        created_by=user.id,
    )
    session.add(audio_version)
    await session.flush()
    audio.current_version_id = audio_version.id
    await session.flush()
    asset = Asset(project_id=project.id, kind="character", name="Hero", version=1)
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="Hero",
        description="",
        metadata_json={},
        status="candidate",
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    await session.flush()
    return {
        "user": user,
        "project": project,
        "asset": asset,
        "audio": audio,
        "binding": binding,
        "voice_binding": voice_binding,
        "version": version,
        "profile": profile,
    }


def _body(**overrides) -> AssetImagePlanBody:
    values = {
        "expected_asset_version": 1,
        "operation": "image_generate",
        "mode_id": "t2i_basic",
        "requirements": AssetCreativeRequirements(
            summary="一位明代书生，青衫长袍", appearance="清瘦，束发", environment="古桥"
        ),
        "parameters": {"aspect_ratio": "9:16"},
        "output_count": 1,
    }
    values.update(overrides)
    return AssetImagePlanBody(**values)


async def test_plan_binds_asset_and_compiles_prompt_without_writes(session, world):
    from app.execution.models import NodeRun

    before = await session.scalar(select(func.count()).select_from(NodeRun))
    plan = await build_asset_image_plan(
        session, project=world["project"], asset_id=world["asset"].id, body=_body()
    )
    after = await session.scalar(select(func.count()).select_from(NodeRun))
    assert before == after == 0
    assert plan.target.kind == "asset"
    assert plan.target.asset_id == world["asset"].id
    assert plan.target.asset_version == 1
    assert plan.stage == "asset_image"
    assert plan.binding_id == world["binding"].id
    assert plan.model_id == "asset-image"
    assert plan.capability == "image.generate"
    assert "一位明代书生" in plan.prompt and "外观：清瘦，束发" in plan.prompt
    assert len(plan.plan_fingerprint) == 64
    assert plan.resolution["status"] == "RESOLVED"
    assert plan.resolution["provider_model_binding_id"] == str(world["binding"].id)
    assert plan.resolution["provider_connection_revision_id"]
    assert plan.resolution["credential_revision_id"]
    assert plan.max_provider_operations == 1


async def test_plan_rejects_stale_version_missing_binding_and_unknown_parameter(
    session, world
):
    with pytest.raises(ConflictError) as stale:
        await build_asset_image_plan(
            session,
            project=world["project"],
            asset_id=world["asset"].id,
            body=_body(expected_asset_version=2),
        )
    assert stale.value.details["code"] == "ASSET_VERSION_CONFLICT"

    world["profile"].image_model_binding_id = None
    await session.flush()
    with pytest.raises(ValidationAppError) as missing:
        await build_asset_image_plan(
            session, project=world["project"], asset_id=world["asset"].id, body=_body()
        )
    assert missing.value.details["code"] == "ASSET_IMAGE_BINDING_MISSING"

    world["profile"].image_model_binding_id = world["binding"].id
    await session.flush()
    with pytest.raises(ValidationAppError) as unknown:
        await build_asset_image_plan(
            session,
            project=world["project"],
            asset_id=world["asset"].id,
            body=_body(parameters={"seed": 42}),
        )
    assert unknown.value.details["code"] == "ASSET_PARAMETER_UNKNOWN"


async def test_plan_rejects_other_projects_assets_and_unsupported_roles(session, world):
    other = Project(
        workspace_id=world["project"].workspace_id,
        name="Other",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(other)
    await session.flush()
    with pytest.raises(NotFoundError):
        await build_asset_image_plan(
            session, project=other, asset_id=world["asset"].id, body=_body()
        )

    reference = AssetVersionReference(
        project_id=world["project"].id,
        asset_version_id=world["version"].id,
        artifact_id=uuid4(),
        reference_role="reference_image",
        label="",
        sort_order=0,
        metadata_json={},
    )
    session.add(reference)
    await session.flush()
    from app.production.asset_plan import AssetImageReference

    with pytest.raises(ValidationAppError) as role:
        await build_asset_image_plan(
            session,
            project=world["project"],
            asset_id=world["asset"].id,
            body=_body(
                references=[
                    AssetImageReference(
                        asset_version_reference_id=reference.id, role="hero"
                    )
                ]
            ),
        )
    assert role.value.details["code"] == "ASSET_REFERENCE_ROLE_UNSUPPORTED"


def test_plan_endpoint_requires_auth_and_an_owned_project(client) -> None:
    from uuid import uuid4 as _uuid4

    from app.shared.security import CSRF_HEADER

    body = {
        "stage": "asset_image",
        "request": {
            "expected_asset_version": 1,
            "operation": "image_generate",
            "mode_id": "t2i_basic",
            "requirements": {"schema_version": 1, "summary": "x"},
            "parameters": {},
            "output_count": 1,
        },
    }
    anonymous = client.post(
        f"/api/v1/projects/{_uuid4()}/assets/{_uuid4()}/execution-plan", json=body
    )
    assert anonymous.status_code in {401, 403}

    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"plan-{_uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Plan Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    csrf = str(client.get("/api/v1/auth/csrf").json()["csrf_token"])
    missing = client.post(
        f"/api/v1/projects/{_uuid4()}/assets/{_uuid4()}/execution-plan",
        json=body,
        headers={CSRF_HEADER: csrf},
    )
    assert missing.status_code == 404


async def test_voice_plan_uses_the_project_voice_binding(session, world):
    from app.production.asset_plan import AssetVoicePlanBody, build_asset_voice_plan

    body = AssetVoicePlanBody(expected_asset_version=1, text="古桥始建于明代。")
    plan = await build_asset_voice_plan(
        session, project=world["project"], asset_id=world["audio"].id, body=body
    )
    assert plan.stage == "asset_voice"
    assert plan.target.kind == "asset"
    assert plan.binding_id == world["voice_binding"].id
    assert plan.model_id == "asset-voice"
    assert plan.voice_options == {"voice_id": "v1"}
    assert len(plan.plan_fingerprint) == 64


async def test_voice_plan_rejects_wrong_kind_and_missing_binding(session, world):
    from app.production.asset_plan import AssetVoicePlanBody, build_asset_voice_plan

    with pytest.raises(ValidationAppError) as kind:
        await build_asset_voice_plan(
            session,
            project=world["project"],
            asset_id=world["asset"].id,
            body=AssetVoicePlanBody(expected_asset_version=1, text="x"),
        )
    assert kind.value.details["code"] == "ASSET_VOICE_KIND"

    world["profile"].voice_model_binding_id = None
    await session.flush()
    with pytest.raises(ValidationAppError) as missing:
        await build_asset_voice_plan(
            session,
            project=world["project"],
            asset_id=world["audio"].id,
            body=AssetVoicePlanBody(expected_asset_version=1, text="x"),
        )
    assert missing.value.details["code"] == "VOICE_BINDING_MISSING"
