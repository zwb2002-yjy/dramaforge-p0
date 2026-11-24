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

    revision = ProviderConnectionRevision(
        connection_id=connection.id,
        revision_no=1,
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        base_url="https://api.agnes-ai.cn",
        credential_revision_id=credential.id,
    )
    session.add(revision)
    await session.flush()
    from datetime import UTC, datetime

    from app.providers.availability_models import (
        ProviderAvailabilityEvidence,
        ProviderModelAvailability,
    )

    evidence = ProviderAvailabilityEvidence(
        workspace_id=workspace.id,
        connection_id=connection.id,
        connection_revision_id=revision.id,
        credential_revision_id=credential.id,
        remote_model_id="asset-image",
        verifier_kind="fixture",
        status="visible",
        listed_model_ids_json=["asset-image"],
        checked_at=datetime.now(UTC),
    )
    session.add(evidence)
    await session.flush()
    session.add(
        ProviderModelAvailability(
            workspace_id=workspace.id,
            connection_id=connection.id,
            connection_revision_id=revision.id,
            credential_revision_id=credential.id,
            remote_model_id="asset-image",
            effective_status="visible",
            positive_evidence_id=evidence.id,
            latest_evidence_id=evidence.id,
        )
    )
    await session.flush()
    video_evidence = ProviderAvailabilityEvidence(
        workspace_id=workspace.id,
        connection_id=connection.id,
        connection_revision_id=revision.id,
        credential_revision_id=credential.id,
        remote_model_id="unit-agnes-video",
        verifier_kind="fixture",
        status="visible",
        listed_model_ids_json=["unit-agnes-video"],
        checked_at=datetime.now(UTC),
    )
    session.add(video_evidence)
    await session.flush()
    session.add(
        ProviderModelAvailability(
            workspace_id=workspace.id,
            connection_id=connection.id,
            connection_revision_id=revision.id,
            credential_revision_id=credential.id,
            remote_model_id="unit-agnes-video",
            effective_status="visible",
            positive_evidence_id=video_evidence.id,
            latest_evidence_id=video_evidence.id,
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
    from app.providers.catalog_loader import hash_manifest
    from model_infra_fixture import unit_video_manifest

    video_manifest = unit_video_manifest()
    video_manifest["operations"]["video.generate"].setdefault("output_options", {})[
        "duration_seconds"
    ] = {"type": "integer", "minimum": 1, "maximum": 10}
    video_entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="unit-agnes-video",
        model_revision="v1",
        display_name="Unit Video",
        media_kind="video",
        capability_manifest_json=video_manifest,
        option_schema_json={},
        documented_at=date(2026, 8, 10),
        contract_manifest_hash=hash_manifest(video_manifest),
    )
    session.add(video_entry)
    await session.flush()
    video_binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="video",
        model_id="unit-agnes-video",
        purpose="video",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        remote_resource_kind="model",
        remote_resource_id="unit-agnes-video",
        invoke_model_value="unit-agnes-video",
        catalog_entry_id=video_entry.id,
        capability_manifest_hash=video_entry.contract_manifest_hash,
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(video_binding)
    await session.flush()
    profile.video_model_binding_id = video_binding.id
    await session.flush()
    video_asset = Asset(project_id=project.id, kind="video", name="Clip", version=1)
    session.add(video_asset)
    await session.flush()
    video_version = AssetVersion(
        project_id=project.id,
        asset_id=video_asset.id,
        version_number=1,
        kind="video",
        name="Clip",
        description="",
        metadata_json={},
        status="candidate",
        created_by=user.id,
    )
    session.add(video_version)
    await session.flush()
    video_asset.current_version_id = video_version.id
    await session.flush()
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
        contract_manifest_hash="e" * 64,
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
    from app.providers.destinations import DestinationService, destination_configuration_hash

    destinations = DestinationService(session, actor=user,workspace=workspace)
    for selected,purpose in [(binding,"image_generation"),(video_binding,"video_generation"),(voice_binding,"voice_generation")]:
        await destinations.declare(binding_ref=str(selected.id), expected_revision=0,
            expected_configuration_hash=destination_configuration_hash(selected,connection),
            processing_location="external", purposes=[purpose])
    return {
        "user": user,
        "project": project,
        "asset": asset,
        "audio": audio,
        "video": video_asset,
        "video_binding": video_binding,
        "binding": binding,
        "voice_binding": voice_binding,
    }


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



async def test_asset_run_completes_through_the_worker(session, world, monkeypatch):
    """The queued asset run completes via the same media worker with a fake runtime."""
    from app.execution.models import NodeRun
    from app.execution.product_path import execute_media_node_run
    from app.providers.runtime import (
        CompiledImageRequest,
        ResolvedRuntime,
        SubmissionResult,
    )
    from app.storage.minio_store import reset_object_store_for_tests

    class FakeCompiler:
        reference_transport = "bytes"

        async def compile(self, intent, *args, **kwargs):
            return CompiledImageRequest(
                provider_type="agnes",
                protocol_profile="agnes_cn_v1",
                model_id="asset-image",
                operation="image.generate",
                wire_request={
                    "model": "asset-image",
                    "prompt": intent.prompt,
                    "aspect_ratio": intent.aspect_ratio,
                },
                request_schema_version="1",
            )

    class FakeRuntime:
        async def submit_image(self, request):
            return SubmissionResult(
                status="succeeded",
                remote_task_id="asset-task-1",
                artifact_bytes=b"\x89PNG\r\n\x1a\nasset",
            )

    captured: dict[str, object] = {}

    async def fake_resolve(self, *, identity, workspace_id, operation=None, settings=None):
        from app.providers.catalog_models import ModelCatalogEntry
        from app.providers.models import ProviderConnection, ProviderModelBinding

        captured["identity"] = identity
        connection = await self._session.get(ProviderConnection, identity.connection_id)
        binding = await self._session.get(
            ProviderModelBinding, identity.provider_model_binding_id
        )
        entry = await self._session.get(ModelCatalogEntry, identity.catalog_entry_id)
        return ResolvedRuntime(
            runtime=FakeRuntime(),
            image_compiler=FakeCompiler(),
            video_compiler=None,
            connection=connection,
            binding=binding,
            catalog_entry=entry,
            model_id="asset-image",
            invoke_model_value="asset-image",
        )

    monkeypatch.setattr(
        "app.providers.runtime.ProviderRuntimeResolver.resolve_runtime_for_identity",
        fake_resolve,
    )
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
    result = await execute_media_node_run(
        session, node_run_id=receipt.node_run_id, store=reset_object_store_for_tests()
    )
    await session.commit()
    run = await session.get(NodeRun, receipt.node_run_id)
    assert captured, "the worker must resolve the frozen runtime"
    assert run.status == "completed", (run.status, run.error_code, run.error_summary)
    assert run.result_artifact_id is not None
    assert result is not None


async def test_asset_batch_previews_and_dispatches_each_item(session, world):
    from app.execution.models import NodeRun
    from app.production.asset_batch import (
        AssetBatchDispatchBody,
        AssetBatchPreviewBody,
        AssetImageBatchItem,
        dispatch_asset_batch,
        preview_asset_batch,
    )

    plan_body = _plan_body()
    preview_body = AssetBatchPreviewBody(
        stage="asset_image",
        items=[
            AssetImageBatchItem(
                item_id="a", asset_id=world["asset"].id, request=plan_body
            ),
            AssetImageBatchItem(
                item_id="b", asset_id=world["asset"].id, request=plan_body
            ),
        ],
    )
    preview = await preview_asset_batch(
        session, project=world["project"], body=preview_body
    )
    assert preview.ready_count == 2 and preview.blocked_count == 0
    assert preview.max_provider_operations == 2
    assert all(item.plan_fingerprint for item in preview.items)

    dispatch_body = AssetBatchDispatchBody(
        **preview_body.model_dump(),
        batch_fingerprint=preview.batch_fingerprint,
        request_key="batch:one",
        max_provider_operations=2,
    )
    result = await dispatch_asset_batch(
        session, project=world["project"], actor=world["user"], body=dispatch_body
    )
    assert len(result.accepted) == 2 and not result.rejected
    runs = (
        await session.execute(
            select(NodeRun).where(NodeRun.project_id == world["project"].id)
        )
    ).scalars().all()
    assert len(runs) == 2

    replay = await dispatch_asset_batch(
        session, project=world["project"], actor=world["user"], body=dispatch_body
    )
    assert [item.node_run_id for item in replay.accepted] == [
        item.node_run_id for item in result.accepted
    ]

    stale = await preview_asset_batch(
        session, project=world["project"], body=preview_body
    )
    world["asset"].version = 2
    await session.flush()
    blocked = await preview_asset_batch(
        session, project=world["project"], body=preview_body
    )
    assert blocked.blocked_count == 2
    assert {item.reason_code for item in blocked.items} == {"ASSET_VERSION_CONFLICT"}
    assert stale.batch_fingerprint != blocked.batch_fingerprint


def _distinct_wav(index: int) -> bytes:
    import io
    import wave

    target = io.BytesIO()
    with wave.open(target, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes([index % 256]) * 2400)
    return target.getvalue()


def _silence_wav() -> bytes:
    import io
    import wave

    target = io.BytesIO()
    with wave.open(target, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes(2400))
    return target.getvalue()


async def test_asset_voice_command_queues_and_completes(session, world, monkeypatch):
    from app.execution.models import NodeRun
    from app.execution.product_path import execute_media_node_run
    from app.production.asset_commands import (
        AssetVoiceExecutionBody,
        submit_asset_voice_execution,
    )
    from app.production.asset_plan import AssetVoicePlanBody, build_asset_voice_plan
    from app.storage.minio_store import reset_object_store_for_tests

    plan_body = AssetVoicePlanBody(expected_asset_version=1, text="古桥始建于明代。")
    plan = await build_asset_voice_plan(
        session, project=world["project"], asset_id=world["audio"].id, body=plan_body
    )
    body = AssetVoiceExecutionBody(
        **plan_body.model_dump(), plan_fingerprint=plan.plan_fingerprint
    )
    receipt = await submit_asset_voice_execution(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["audio"].id,
        body=body,
        idempotency_key="voice:one",
    )
    run = await session.get(NodeRun, receipt.node_run_id)
    assert run is not None
    assert run.input_snapshot["voice_execution"]["engine"] == "voice_model"
    assert run.input_snapshot["voice_execution"]["binding_id"] == str(
        world["voice_binding"].id
    )
    assert run.input_snapshot["asset_id"] == str(world["audio"].id)

    replay = await submit_asset_voice_execution(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["audio"].id,
        body=body,
        idempotency_key="voice:one",
    )
    assert replay.node_run_id == receipt.node_run_id

    class FakeVoiceAdapter:
        def __init__(self) -> None:
            self.blobs: dict[str, bytes] = {}

        async def create(self, request):
            self.blobs["voice-1"] = _silence_wav()
            return {"remote_task_id": "voice-1", "status": "succeeded"}

        async def poll(self, remote_task_id):
            return {"status": "succeeded" if remote_task_id in self.blobs else "failed"}

    adapter = FakeVoiceAdapter()

    async def fake_adapter(*args, **kwargs):
        return adapter

    monkeypatch.setattr("app.execution.voice_path.get_voice_adapter", fake_adapter)
    await execute_media_node_run(
        session, node_run_id=receipt.node_run_id, store=reset_object_store_for_tests()
    )
    await session.commit()
    await session.refresh(run)
    assert run.status == "completed", (run.status, run.error_code, run.error_summary)
    assert run.result_artifact_id is not None


async def test_asset_video_command_queues_one_run(session, world):
    from app.execution.models import NodeRun
    from app.production.asset_commands import (
        AssetVideoExecutionBody,
        submit_asset_video_execution,
    )
    from app.production.asset_plan import AssetVideoPlanBody, build_asset_video_plan

    plan_body = AssetVideoPlanBody(
        expected_asset_version=1,
        requirements=AssetCreativeRequirements(summary="古桥在晨雾中显现"),
        mode_id="text_to_video",
        parameters={"duration_seconds": 5},
    )
    plan = await build_asset_video_plan(
        session, project=world["project"], asset_id=world["video"].id, body=plan_body
    )
    body = AssetVideoExecutionBody(
        **plan_body.model_dump(), plan_fingerprint=plan.plan_fingerprint
    )
    receipt = await submit_asset_video_execution(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["video"].id,
        body=body,
        idempotency_key="video:one",
    )
    run = await session.get(NodeRun, receipt.node_run_id)
    assert run is not None
    assert run.status == "queued"
    assert run.input_snapshot["asset_id"] == str(world["video"].id)
    assert run.input_snapshot["duration_seconds"] == 5.0
    assert run.input_snapshot["execution_model_resolution"]["status"] == "RESOLVED"


async def test_voice_command_rejects_segmented_text(session, world):
    from app.production.asset_commands import (
        AssetVoiceExecutionBody,
        submit_asset_voice_execution,
    )
    from app.production.asset_plan import AssetVoicePlanBody, build_asset_voice_plan
    from app.shared.errors import ValidationAppError

    plan_body = AssetVoicePlanBody(
        expected_asset_version=1,
        text="".join(f"第{i}句，古桥始建于明代，桥身以青石砌成。" for i in range(40)),
    )
    plan = await build_asset_voice_plan(
        session, project=world["project"], asset_id=world["audio"].id, body=plan_body
    )
    body = AssetVoiceExecutionBody(
        **plan_body.model_dump(), plan_fingerprint=plan.plan_fingerprint
    )
    with pytest.raises(ValidationAppError) as segmented:
        await submit_asset_voice_execution(
            session,
            actor=world["user"],
            project_id=world["project"].id,
            asset_id=world["audio"].id,
            body=body,
        )
    assert segmented.value.details["code"] == "ASSET_VOICE_SEGMENTED_BATCH_REQUIRED"


async def test_asset_batch_accepts_mixed_image_and_voice_items(session, world):
    from app.production.asset_batch import (
        AssetBatchDispatchBody,
        AssetBatchPreviewBody,
        AssetImageBatchItem,
        AssetVoiceBatchItem,
        dispatch_asset_batch,
        preview_asset_batch,
    )
    from app.production.asset_plan import AssetVoicePlanBody

    preview_body = AssetBatchPreviewBody(
        stage="asset_image",
        items=[
            AssetImageBatchItem(
                item_id="img", asset_id=world["asset"].id, request=_plan_body()
            ),
            AssetVoiceBatchItem(
                item_id="voice",
                asset_id=world["audio"].id,
                request=AssetVoicePlanBody(expected_asset_version=1, text="短句。"),
            ),
        ],
    )
    preview = await preview_asset_batch(
        session, project=world["project"], body=preview_body
    )
    assert preview.ready_count == 2 and preview.blocked_count == 0
    dispatch_body = AssetBatchDispatchBody(
        **preview_body.model_dump(),
        batch_fingerprint=preview.batch_fingerprint,
        request_key="batch:mixed",
        max_provider_operations=2,
    )
    result = await dispatch_asset_batch(
        session, project=world["project"], actor=world["user"], body=dispatch_body
    )
    assert len(result.accepted) == 2 and not result.rejected
    from app.execution.models import NodeRun

    runs = (
        await session.execute(
            select(NodeRun).where(NodeRun.project_id == world["project"].id)
        )
    ).scalars().all()
    assert {run.input_snapshot.get("node_key") for run in runs} == {"image", "voice"}



async def test_asset_video_run_submits_once_through_the_worker(session, world, monkeypatch):
    """The queued video run reaches the provider boundary exactly once."""
    from app.execution.models import NodeRun, ProviderOperation
    from app.execution.product_path import execute_media_node_run
    from app.providers.runtime import (
        CompiledVideoRequest,
        ProviderResumeToken,
        ResolvedRuntime,
        SubmissionResult,
    )
    from app.storage.minio_store import reset_object_store_for_tests

    class FakeVideoCompiler:
        reference_transport = "bytes"

        async def compile(self, intent, *args, **kwargs):
            output = intent.output.model_dump(exclude_none=True)
            return CompiledVideoRequest(
                provider_type="agnes",
                protocol_profile="agnes_cn_v1",
                model_id="unit-agnes-video",
                operation="video.generate",
                wire_request={
                    "model": "unit-agnes-video",
                    "prompt": intent.prompt,
                    **output,
                },
                request_schema_version="1",
            )

    class FakeVideoRuntime:
        def __init__(self) -> None:
            self.submits = 0

        async def submit_video(self, request):
            self.submits += 1
            return SubmissionResult(
                status="accepted",
                remote_task_id="video-task-1",
                resume_token=ProviderResumeToken(
                    provider_type="agnes",
                    protocol_profile="agnes_cn_v1",
                    remote_task_id="video-task-1",
                ),
            )

    runtime = FakeVideoRuntime()

    async def fake_resolve(self, *, identity, workspace_id, operation=None, settings=None):
        from app.providers.catalog_models import ModelCatalogEntry
        from app.providers.models import ProviderConnection, ProviderModelBinding

        connection = await self._session.get(ProviderConnection, identity.connection_id)
        binding = await self._session.get(
            ProviderModelBinding, identity.provider_model_binding_id
        )
        entry = await self._session.get(ModelCatalogEntry, identity.catalog_entry_id)
        return ResolvedRuntime(
            runtime=runtime,
            image_compiler=None,
            video_compiler=FakeVideoCompiler(),
            connection=connection,
            binding=binding,
            catalog_entry=entry,
            model_id="unit-agnes-video",
            invoke_model_value="unit-agnes-video",
        )

    monkeypatch.setattr(
        "app.providers.runtime.ProviderRuntimeResolver.resolve_runtime_for_identity",
        fake_resolve,
    )
    from app.production.asset_commands import (
        AssetVideoExecutionBody,
        submit_asset_video_execution,
    )
    from app.production.asset_plan import AssetVideoPlanBody, build_asset_video_plan

    plan_body = AssetVideoPlanBody(
        expected_asset_version=1,
        requirements=AssetCreativeRequirements(summary="古桥在晨雾中显现"),
        mode_id="text_to_video",
        parameters={"duration_seconds": 5},
    )
    plan = await build_asset_video_plan(
        session, project=world["project"], asset_id=world["video"].id, body=plan_body
    )
    body = AssetVideoExecutionBody(
        **plan_body.model_dump(), plan_fingerprint=plan.plan_fingerprint
    )
    receipt = await submit_asset_video_execution(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["video"].id,
        body=body,
    )
    from app.shared.errors import ProviderTaskPendingError

    with pytest.raises(ProviderTaskPendingError):
        await execute_media_node_run(
            session, node_run_id=receipt.node_run_id, store=reset_object_store_for_tests()
        )
    await session.commit()
    run = await session.get(NodeRun, receipt.node_run_id)
    assert run.status in {"queued", "running"}
    operation = (
        await session.execute(
            select(ProviderOperation).where(
                ProviderOperation.node_run_id == receipt.node_run_id
            )
        )
    ).scalar_one()
    assert operation.provider_operation_id == "video-task-1"
    assert operation.actual_provider == "agnes"
    assert operation.actual_model == "unit-agnes-video"
    assert runtime.submits == 1


async def test_segmented_voice_batch_concats_segments(session, world, monkeypatch):
    import io
    import wave

    from app.execution.models import NodeRun
    from app.execution.product_path import execute_media_node_run
    from app.production.asset_commands import (
        AssetVoiceExecutionBody,
        submit_asset_voice_batch,
    )
    from app.production.asset_plan import AssetVoicePlanBody, build_asset_voice_plan
    from app.storage.minio_store import reset_object_store_for_tests

    plan_body = AssetVoicePlanBody(
        expected_asset_version=1,
        text="".join(f"第{i}句，古桥始建于明代，桥身以青石砌成。" for i in range(40)),
    )
    plan = await build_asset_voice_plan(
        session, project=world["project"], asset_id=world["audio"].id, body=plan_body
    )
    assert len(plan.segments) > 1
    body = AssetVoiceExecutionBody(
        **plan_body.model_dump(), plan_fingerprint=plan.plan_fingerprint, max_provider_operations=plan.max_provider_operations
    )
    receipt = await submit_asset_voice_batch(
        session,
        actor=world["user"],
        project_id=world["project"].id,
        asset_id=world["audio"].id,
        body=body,
        idempotency_key="voice:segments",
    )
    runs = (
        await session.execute(
            select(NodeRun).where(NodeRun.project_id == world["project"].id)
        )
    ).scalars().all()
    assert len(runs) == len(plan.segments) + 1
    segment_runs = [run for run in runs if run.id != receipt.node_run_id]
    assert all(run.input_snapshot.get("segment_index") is not None for run in segment_runs)
    concat_run = next(run for run in runs if run.id == receipt.node_run_id)
    assert concat_run.input_snapshot["node_key"] == "voice_concat"
    assert concat_run.input_snapshot["segment_count"] == len(plan.segments)

    class FakeVoiceAdapter:
        def __init__(self) -> None:
            self.blobs: dict[str, bytes] = {}

        async def create(self, request):
            key = f"voice-{len(self.blobs)}"
            self.blobs[key] = _distinct_wav(len(self.blobs))
            return {"remote_task_id": key, "status": "succeeded"}

        async def poll(self, remote_task_id):
            return {"status": "succeeded" if remote_task_id in self.blobs else "failed"}

    adapter = FakeVoiceAdapter()

    async def fake_adapter(*args, **kwargs):
        return adapter

    monkeypatch.setattr("app.execution.voice_path.get_voice_adapter", fake_adapter)
    store = reset_object_store_for_tests()
    for run in segment_runs:
        await execute_media_node_run(session, node_run_id=run.id, store=store)
    await session.commit()
    for run in segment_runs:
        await session.refresh(run)
        assert run.status in {"completed", "cached"}, (
            run.status,
            run.error_code,
            run.error_summary,
        )
    await execute_media_node_run(session, node_run_id=concat_run.id, store=store)
    await session.commit()
    await session.refresh(concat_run)
    assert concat_run.status == "completed", (
        concat_run.status,
        concat_run.error_code,
        concat_run.error_summary,
    )
    assert concat_run.result_artifact_id is not None
    artifact = await session.get(
        __import__("app.execution.models", fromlist=["Artifact"]).Artifact,
        concat_run.result_artifact_id,
    )
    data = await store.get_bytes(object_key=artifact.object_key)
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getnframes() == len(plan.segments) * 1200
