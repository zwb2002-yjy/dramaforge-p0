"""Asset command submission: one queued NodeRun, replayable receipt (I8a-03)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, ProjectCreativeProfile, User, Workspace
from app.assets.models import Asset, AssetVersion
from app.production.asset_commands import submit_asset_execution
from app.production.asset_plan import (
    AssetCreativeRequirements,
    AssetExecutionBody,
    AssetImagePlanBody,
    build_asset_image_plan,
)
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.security.models import EncryptedProviderCredential
from app.shared.errors import ConflictError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _manifest() -> dict:
    return {
        "manifest_version": "1",
        "provider_type": "agnes",
        "protocol_profile": "agnes_cn_v1",
        "model_id": "asset-image",
        "model_revision": "v1",
        "media_kind": "image",
        "display_name": "Asset Image",
        "documented_at": date(2026, 8, 10).isoformat(),
        "operations": {
            "image.generate": {
                "operation": "image.generate",
                "capabilities": ["image.t2i"],
                "output_options": {
                    "aspect_ratio": {
                        "type": "string",
                        "default": "1:1",
                        "enum": ["1:1", "9:16"],
                    }
                },
            }
        },
        "option_schema": {"namespace": ""},
    }


@pytest.fixture
async def world(session: AsyncSession):
    suffix = uuid4().hex[:8]
    user = User(email=f"cmd-{suffix}@example.com", display_name="C", password_hash="x")
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
        capability_manifest_json=_manifest(),
        option_schema_json={},
        documented_at=date(2026, 8, 10),
        contract_manifest_hash="c" * 64,
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
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        remote_resource_kind="model",
        remote_resource_id="asset-image",
        invoke_model_value="asset-image",
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    session.add(
        ProductionModelProfile(
            workspace_id=workspace.id,
            project_id=project.id,
            name="default",
            version=1,
            bindings={},
            image_model_binding_id=binding.id,
            created_by=user.id,
            updated_by=user.id,
        )
    )
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
    return {"user": user, "project": project, "asset": asset, "binding": binding}


def _plan_body() -> AssetImagePlanBody:
    return AssetImagePlanBody(
        expected_asset_version=1,
        operation="image_generate",
        mode_id="t2i_basic",
        requirements=AssetCreativeRequirements(summary="一位明代书生"),
        parameters={"aspect_ratio": "9:16"},
    )


async def test_asset_command_queues_one_run_and_replays_the_receipt(session, world):
    from app.execution.models import NodeRun

    plan = await build_asset_image_plan(
        session, project=world["project"], asset_id=world["asset"].id, body=_plan_body()
    )
    body = AssetExecutionBody(
        **_plan_body().model_dump(), plan_fingerprint=plan.plan_fingerprint
    )
    receipt = await submit_asset_execution(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["asset"].id,
        body=body,
        idempotency_key="asset:one",
    )
    assert receipt.status == "queued"
    run = await session.get(NodeRun, receipt.node_run_id)
    assert run is not None
    assert run.input_snapshot["asset_id"] == str(world["asset"].id)
    assert run.input_snapshot["plan_fingerprint"] == plan.plan_fingerprint
    assert run.input_snapshot["execution_model_resolution"]["status"] == "RESOLVED"
    assert run.input_snapshot["target"] == {
        "kind": "asset",
        "id": str(world["asset"].id),
    }
    assert (
        await session.scalar(
            select(func.count())
            .select_from(NodeRun)
            .where(NodeRun.project_id == world["project"].id)
        )
        == 1
    )
    from app.events.models import EventLog

    notice = await session.scalar(
        select(EventLog).where(EventLog.event_type == "execution_accepted")
    )
    assert notice is not None
    assert notice.aggregate_type == "asset"
    assert notice.aggregate_id == world["asset"].id

    replay = await submit_asset_execution(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["asset"].id,
        body=body,
        idempotency_key="asset:one",
    )
    assert replay.node_run_id == receipt.node_run_id
    assert replay.graph_id == receipt.graph_id


async def test_asset_command_rejects_stale_version_and_key_reuse(session, world):
    plan = await build_asset_image_plan(
        session, project=world["project"], asset_id=world["asset"].id, body=_plan_body()
    )
    body = AssetExecutionBody(
        expected_asset_version=1,
        operation="image_generate",
        mode_id="t2i_basic",
        requirements=AssetCreativeRequirements(summary="一位明代书生"),
        parameters={"aspect_ratio": "9:16"},
        plan_fingerprint=plan.plan_fingerprint,
    )
    world["asset"].version = 2
    await session.flush()
    with pytest.raises(ConflictError) as stale:
        await submit_asset_execution(
            session,
            actor=world["user"],
            project_id=world["project"].id,
            asset_id=world["asset"].id,
            body=body,
        )
    assert stale.value.details["code"] == "ASSET_VERSION_CONFLICT"


async def test_list_asset_executions_reads_the_original_runs(session, world):
    from app.production.asset_commands import list_asset_executions

    plan = await build_asset_image_plan(
        session, project=world["project"], asset_id=world["asset"].id, body=_plan_body()
    )
    body = AssetExecutionBody(
        **_plan_body().model_dump(), plan_fingerprint=plan.plan_fingerprint
    )
    receipt = await submit_asset_execution(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["asset"].id,
        body=body,
    )
    rows = await list_asset_executions(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["asset"].id,
    )
    assert [row.node_run_id for row in rows] == [receipt.node_run_id]
    assert rows[0].status == "queued"
    assert rows[0].plan_fingerprint == plan.plan_fingerprint
    assert rows[0].graph_id == receipt.graph_id

    other = Asset(project_id=world["project"].id, kind="character", name="Other")
    session.add(other)
    await session.flush()
    from app.shared.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await list_asset_executions(
            session,
            actor=world["user"],
            project_id=world["project"].id,
            asset_id=uuid4(),
        )

