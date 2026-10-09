"""Persisted @labels through Workbench plans and the actual Worker HTTP compiler."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO

import httpx
import pytest
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.config import Settings
from app.contracts.production_commands import ExecutionBody
from app.execution.media_submission import prepare_media_submission
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.production.application.commands import ProductionCommands
from app.production.models import ShotReferenceBinding
from app.production.reference_intents import ShotReferenceIntent
from app.production.workbench_execution import WorkbenchExecutionError, WorkbenchExecutionService
from app.providers.agnes import AgnesImageCompiler, AgnesRuntime
from app.providers.catalog_loader import hash_manifest
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.models import ProviderConnection
from app.providers.runtime import ProviderRuntimeResolver, ResolvedRuntime
from app.shared.errors import ValidationAppError
from PIL import Image
from sqlalchemy import func, select
from tests.unit.test_workbench_execution import _input, _seed, _seed_image_shot
from tests.unit.test_workbench_execution import session as session


async def _setup(session, count=1, *, supported=1):
    project, video_binding, user = await _seed(session)
    shot, _, image_binding = await _seed_image_shot(
        session, project=project, user=user, connection_id=video_binding.connection_id
    )
    entry = await session.get(ModelCatalogEntry, image_binding.catalog_entry_id)
    if supported > 1:
        # An isolated Mock Provider contract declares multi-image input explicitly.
        # Current shipped single-image manifests stay unchanged and reject extras.
        manifest = dict(entry.capability_manifest_json)
        manifest["operations"] = {
            "image.generate": {
                "operation": "image.generate",
                "capabilities": ["image.i2i"],
                "input_contracts": {
                    "multiple": {
                        "input_slots": {
                            "reference_image": {
                                "minimum": 1,
                                "maximum": supported,
                                "media_types": ["image/*"],
                            }
                        },
                        "minimum_total_references": 1,
                        "common_options": {
                            "size": {"type": "string", "default": "1K", "enum": ["1K"]},
                            "aspect_ratio": {"type": "string", "default": "9:16", "enum": ["9:16"]},
                        },
                        "native_options": {
                            "response_format": {"type": "string", "default": "url", "enum": ["url"]}
                        },
                    }
                },
            }
        }
        entry.capability_manifest_json = manifest
        entry.contract_manifest_hash = hash_manifest(manifest)
        image_binding.capability_manifest_hash = entry.contract_manifest_hash
    blobs = {}
    intents = []
    bindings = []
    assets = []
    for index in range(count):
        buffer = BytesIO()
        Image.new("RGB", (1, 1), (index + 1, 20, 30)).save(buffer, "PNG")
        content = buffer.getvalue()
        asset = Asset(
            project_id=project.id,
            kind="character",
            name=f"角色{index + 1}",
            status="active",
            metadata_json={},
        )
        session.add(asset)
        await session.flush()
        version = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=1,
            kind="character",
            name=asset.name,
            status="formal",
            metadata_json={},
            created_by=user.id,
        )
        session.add(version)
        await session.flush()
        asset.current_version_id = version.id
        artifact = Artifact(
            project_id=project.id,
            artifact_type="image",
            storage_state="available",
            object_key=f"mention/{index}",
            content_hash=hashlib.sha256(content).hexdigest(),
            mime_type="image/png",
            byte_size=len(content),
            width=1,
            height=1,
        )
        session.add(artifact)
        await session.flush()
        session.add(
            AssetVersionReference(
                project_id=project.id,
                asset_version_id=version.id,
                artifact_id=artifact.id,
                reference_role="front_face",
                sort_order=0,
                label="正面",
                metadata_json={},
            )
        )
        binding = ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot.id,
            stage="image",
            asset_id=asset.id,
            purpose="identity",
            label=f"@角色{index + 1}",
            sort_order=index,
            resolution_mode="current_formal",
            metadata_json={},
            created_by=user.id,
        )
        session.add(binding)
        await session.flush()
        blobs[artifact.object_key] = content
        intents.append(
            ShotReferenceIntent(
                binding_id=binding.id,
                asset_version_id=version.id,
                artifact_id=artifact.id,
                purpose="identity",
            )
        )
        bindings.append(binding)
        assets.append(asset)
    shot.image_prompt = " 与 ".join(binding.label for binding in bindings) + " 在窗边交谈"
    await session.flush()
    command = _input(
        shot_id=shot.id,
        stage="image_keyframe",
        prompt=shot.image_prompt,
        requested_binding_id=image_binding.id,
        expected_shot_version=shot.version,
        mode_id="text_to_image",
        references=list(reversed(intents)),
    )
    return project, user, shot, image_binding, entry, command, bindings, assets, blobs


@pytest.mark.parametrize("count", [1, 2])
async def test_mentions_reach_the_actual_http_body_in_saved_order(session, monkeypatch, count):
    project, user, shot, binding, entry, command, bindings, assets, blobs = await _setup(
        session, count, supported=count
    )
    service = WorkbenchExecutionService(session, user_id=user.id)
    plan = await service.build_plan(project=project, execution_input=command)
    assert plan.prompt == " 与 ".join(f"参考图片{i + 1}" for i in range(count)) + " 在窗边交谈"
    assert [ref.binding_id for ref in plan.planned_references] == [row.id for row in bindings]
    mapping = plan.semantic_intent["prompt_reference_map"]
    assert [row["asset_id"] for row in mapping] == [str(asset.id) for asset in assets]
    assert [row["ordinal"] for row in mapping] == list(range(1, count + 1))
    run = await service.create_and_dispatch(
        project=project, execution_input=command, prepared_plan=plan
    )
    captured = []

    def receive(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"url": "https://output.invalid/result.png"}]})

    runtime = AgnesRuntime(
        settings=Settings(agnes_enabled=True, agnes_api_key="isolated-mock-key"),
        transport=httpx.MockTransport(receive),
    )
    connection = await session.get(ProviderConnection, binding.connection_id)
    resolved = ResolvedRuntime(
        runtime=runtime,
        image_compiler=AgnesImageCompiler(),
        video_compiler=None,
        connection=connection,
        binding=binding,
        catalog_entry=entry,
        model_id=binding.model_id,
        invoke_model_value=binding.invoke_model_value,
        manifest_hash=entry.contract_manifest_hash,
    )

    async def resolve(_self, **kwargs):
        assert kwargs["workspace_id"] == project.workspace_id
        return resolved

    monkeypatch.setattr(ProviderRuntimeResolver, "resolve_runtime_for_resolution", resolve)
    monkeypatch.setattr(ProviderRuntimeResolver, "resolve_runtime_for_identity", resolve)

    class Store:
        async def get_bytes(self, *, object_key):
            return blobs[object_key]

    # Rename mutable Assets after acceptance: the Worker still consumes the exact
    # frozen Artifact identities and prompt, never a new name/version lookup.
    for index, asset in enumerate(assets):
        asset.name = f"验收后改名{index + 1}"
        bindings[index].label = f"@验收后标签{index + 1}"
        bindings[index].version += 1
        new_version = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=2,
            kind="character",
            name=asset.name,
            status="formal",
            metadata_json={},
            created_by=user.id,
        )
        session.add(new_version)
        await session.flush()
        asset.current_version_id = new_version.id
    await session.flush()
    prepared = await prepare_media_submission(
        session,
        project=project,
        run=run,
        node_type="keyframe",
        snap=dict(run.input_snapshot),
        obj_store=Store(),
        prompt=plan.prompt,
        canonical_image_bytes=None,
        has_canonical_binding=False,
        canonical_artifact=None,
        frozen_identity=None,
        workbench_plan=plan,
        op=None,
        now=datetime.now(UTC),
    )
    assert captured == []  # Preparation is not a Provider create.
    result = await prepared.runtime.submit_image(prepared.compiled)
    assert result.status == "succeeded"
    assert captured[0]["prompt"] == plan.prompt
    assert prepared.compiled.reference_artifact_ids == [
        ref.artifact_id for ref in plan.planned_references
    ]
    assert prepared.identity_json["connection_revision_id"] == str(plan.connection_revision_id)
    assert prepared.identity_json["credential_revision_id"] == str(plan.credential_revision_id)
    # Decode only inside the test; image bytes never enter console/evidence output.
    import base64

    delivered = captured[0]["extra_body"]["image"]
    assert len(delivered) == count
    assert [
        hashlib.sha256(base64.b64decode(value.split(",", 1)[1])).hexdigest() for value in delivered
    ] == [ref.fingerprint for ref in plan.planned_references]


async def test_unbound_mentions_fail_before_any_graph_run_or_provider_operation(session):
    project, user, shot, _, _, command, _, _, _ = await _setup(session)
    shot.image_prompt = "@未绑定角色走进房间"
    command = command.model_copy(update={"prompt": shot.image_prompt})
    with pytest.raises(WorkbenchExecutionError) as failure:
        await WorkbenchExecutionService(session, user_id=user.id).build_plan(
            project=project, execution_input=command
        )
    assert failure.value.details["code"] == "REFERENCE_MENTION_UNRESOLVED"
    assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0
    assert await session.scalar(select(func.count()).select_from(ProviderOperation)) == 0


async def test_single_image_manifest_rejects_multi_reference_requests(session):
    project, user, _, _, _, command, _, _, _ = await _setup(session, 2)
    with pytest.raises(WorkbenchExecutionError) as failure:
        await WorkbenchExecutionService(session, user_id=user.id).build_plan(
            project=project, execution_input=command
        )
    assert "capability gaps" in str(failure.value)
    assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0


async def test_changed_order_changes_prompt_ordinals_and_invalidates_the_old_plan(session):
    project, user, shot, _, _, command, bindings, _, _ = await _setup(session, 2, supported=2)
    service = WorkbenchExecutionService(session, user_id=user.id)
    before = await service.build_plan(project=project, execution_input=command)
    bindings[0].sort_order = 3
    bindings[0].version += 1
    await session.flush()
    after = await service.build_plan(project=project, execution_input=command)
    assert after.prompt.startswith("参考图片2 与 参考图片1")
    assert after.plan_fingerprint != before.plan_fingerprint
    with pytest.raises(ValidationAppError) as failure:
        await ProductionCommands(session).submit_user_execution(
            actor=user,
            project_id=project.id,
            shot_id=shot.id,
            command_key="changed-order",
            body=ExecutionBody(
                stage=command.stage,
                prompt=command.prompt,
                mode_id=command.mode_id,
                requested_binding_id=command.requested_binding_id,
                references=command.references,
                expected_shot_version=shot.version,
                plan_fingerprint=before.plan_fingerprint,
                semantic_intent=command.semantic_intent,
            ),
        )
    assert failure.value.details["code"] == "PLAN_FINGERPRINT_MISMATCH"
    assert await session.scalar(select(func.count()).select_from(NodeRun)) == 0
