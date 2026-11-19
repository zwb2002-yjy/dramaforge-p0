"""One shared asset reaches both episodes' Provider submissions (I8b).

The earlier slices prove the shared reference is planned and frozen the same way
for both episodes.  This one follows the same frozen reference through the real
Worker media path (``execute_media_node_run``) into the Provider request, so the
sharing is verified at the paid boundary rather than only in a snapshot: both
episodes submit the identical asset bytes, each keeps its own generated
keyframe, and the Asset keeps exactly one formal version.
"""

from __future__ import annotations

import base64
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import (
    Asset,
    AssetVersion,
    AssetVersionReference,
    Episode,
    Scene,
    Shot,
)
from app.contracts.shot_reference import ShotReferenceIntent
from app.production.models import ShotReferenceBinding
from app.production.workbench_execution import (
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

IMAGE_MODEL_ID = "agnes-image-2.5-flash"
DATA_URI_PREFIX = "data:image/png;base64,"


def _png(color: str = "red") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1024, 1024), color).save(buffer, "PNG")
    return buffer.getvalue()


async def _two_episode_shots(session: AsyncSession) -> tuple[Project, User, list[Shot]]:
    suffix = uuid4().hex[:8]
    user = User(email=f"submit-{suffix}@example.com", display_name="S", password_hash="x")
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
        work_type="serial_comic",
        planned_episode_count=2,
    )
    session.add(project)
    await session.flush()
    shots: list[Shot] = []
    for episode_number in (1, 2):
        episode = Episode(
            project_id=project.id,
            episode_number=episode_number,
            title=f"E{episode_number}",
            synopsis="",
        )
        session.add(episode)
        await session.flush()
        scene = Scene(
            episode_id=episode.id,
            scene_number=1,
            location_name="Studio",
            time_of_day="day",
            synopsis="",
        )
        session.add(scene)
        await session.flush()
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=1,
            sort_order=1,
            shot_type="wide",
            camera_move="static",
            status="draft",
            visual_description="frame",
            dialogue="",
            duration_seconds=5,
            image_prompt="frame",
            video_prompt="motion",
        )
        session.add(shot)
        shots.append(shot)
    await session.flush()
    return project, user, shots


async def _agnes_image_binding(session: AsyncSession, *, project: Project, owner: User):
    """One Agnes image connection with a decryptable frozen credential revision."""
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_sync import sync_model_catalog
    from app.providers.connection_service import ProviderConnectionService
    from app.providers.models import ProviderConnection, ProviderConnectionRevision
    from app.providers.workspace_credentials import configured_byok_keyring
    from app.security.credentials import store_credential

    credential = await store_credential(
        session,
        workspace_id=project.workspace_id,
        provider="agnes",
        plaintext="fixture-agnes-key",
        keyring=configured_byok_keyring(),
    )
    connection = ProviderConnection(
        workspace_id=project.workspace_id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=credential.id,
        credential_revision=credential.revision_no,
        enabled=True,
        verification_status="verified",
        created_by=owner.id,
        updated_by=owner.id,
    )
    session.add(connection)
    await session.flush()
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
    await sync_model_catalog(session, apply=True)
    entry = (
        await session.scalars(
            select(ModelCatalogEntry).where(
                ModelCatalogEntry.model_id == IMAGE_MODEL_ID,
                ModelCatalogEntry.lifecycle == "active",
            )
        )
    ).one()
    service = ProviderConnectionService(session)
    # A create needs positive visibility evidence for this exact revision.
    await service.probe(
        workspace_id=project.workspace_id,
        connection_id=connection.id,
        actor=owner,
        capability="auth_models",
    )
    return await service.create_model_binding(
        workspace_id=project.workspace_id,
        connection_id=connection.id,
        actor=owner,
        model_id=IMAGE_MODEL_ID,
        media_type="image",
        purpose="keyframe",
        capability_contract_id=entry.id,
        enabled=True,
    )


async def _shared_asset_reference(
    session: AsyncSession,
    *,
    project: Project,
    owner: User,
    shots: list[Shot],
    store,
) -> tuple[Asset, AssetVersion, object, bytes]:
    """One character asset, one formal version, one reference artifact."""
    from app.execution.models import Artifact

    shared_png = _png("red")
    stored = await store.put_bytes(
        object_key=f"obj/{uuid4().hex}",
        data=shared_png,
        mime_type="image/png",
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
        status="formal",
        created_by=owner.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type="image/png",
        byte_size=stored.byte_size,
    )
    session.add(artifact)
    await session.flush()
    session.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=artifact.id,
            reference_role="front_face",
            label="front",
            sort_order=0,
            metadata_json={},
        )
    )
    for shot in shots:
        session.add(
            ShotReferenceBinding(
                project_id=project.id,
                shot_id=shot.id,
                stage="image",
                asset_id=asset.id,
                resolution_mode="current_formal",
                purpose="identity",
                label="Hero",
                metadata_json={},
                created_by=owner.id,
            )
        )
    await session.flush()
    return asset, version, artifact, shared_png


def _submission_input(
    project: Project, *, shot: Shot, binding_id, reference: ShotReferenceIntent
) -> WorkbenchExecutionInput:
    return WorkbenchExecutionInput(
        project_id=project.id,
        shot_id=shot.id,
        stage="image_keyframe",
        prompt="frame",
        semantic_intent={"intent": "shot_keyframe"},
        mode_id="text_to_image",
        requested_binding_id=binding_id,
        expected_shot_version=shot.version,
        references=[reference],
    )


@pytest.mark.asyncio
async def test_shared_asset_reaches_both_episode_provider_submissions(
    session: AsyncSession, monkeypatch
) -> None:
    import json

    from app.config import clear_settings_cache
    from app.execution import media_io
    from app.execution.models import Artifact, ProviderOperation
    from app.execution.product_path import execute_media_node_run
    from app.storage.minio_store import reset_object_store_for_tests
    from cryptography.fernet import Fernet

    # One frozen bearer revision per workspace, decryptable in this process only.
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    clear_settings_cache()

    store = reset_object_store_for_tests()
    project, owner, shots = await _two_episode_shots(session)
    # Each episode's keyframe must be its own bytes; identical media would be
    # rejected by the independence guard rather than counted twice.
    generated = {"/1.png": _png("green"), "/2.png": _png("blue")}
    submitted: list[httpx.Request] = []

    def receive(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer fixture-agnes-key"
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json={"data": [{"id": IMAGE_MODEL_ID}]})
        assert request.url.path == "/v1/images/generations"
        submitted.append(request)
        return httpx.Response(
            200, json={"data": [{"url": f"https://media.example/{len(submitted)}.png"}]}
        )

    async def download_result(*, kind: str, artifact_uri: str, destination):
        suffix = next(key for key in generated if artifact_uri.endswith(key))

        async def chunks():
            yield generated[suffix]

        return await media_io._materialize_provider_media(
            kind=kind,
            chunks=chunks(),
            destination=destination,
            content_type="image/png",
        )

    monkeypatch.setattr(
        "app.providers.egress.guarded_provider_transport",
        lambda **kwargs: httpx.MockTransport(receive),
    )
    monkeypatch.setattr(media_io, "_download_provider_media", download_result)

    binding = await _agnes_image_binding(session, project=project, owner=owner)
    asset, version, artifact, shared_png = await _shared_asset_reference(
        session, project=project, owner=owner, shots=shots, store=store
    )
    await session.commit()

    workbench = WorkbenchExecutionService(session, user_id=owner.id)
    planned_artifacts: list[str] = []
    runs = []
    for shot in shots:
        shot_binding = (
            await session.scalars(
                select(ShotReferenceBinding).where(ShotReferenceBinding.shot_id == shot.id)
            )
        ).one()
        reference = ShotReferenceIntent(
            binding_id=shot_binding.id,
            purpose="identity",
            asset_version_id=version.id,
            artifact_id=artifact.id,
            mime_type="image/png",
        )
        command = _submission_input(project, shot=shot, binding_id=binding.id, reference=reference)
        plan = await workbench.build_plan(project=project, execution_input=command)
        assert len(plan.planned_references) == 1
        assert plan.planned_references[0].role == "reference_image"
        planned_artifacts.append(str(plan.planned_references[0].artifact_id))
        proof = await workbench.preview_compiler_contract(project=project, plan=plan)
        assert proof is not None and proof.wire_fingerprint is not None
        runs.append(
            await workbench.create_and_dispatch(
                project=project,
                execution_input=command,
                prepared_plan=plan,
                confirmed_compiler_wire_fingerprint=proof.wire_fingerprint,
            )
        )
    await session.commit()
    assert planned_artifacts == [str(artifact.id), str(artifact.id)]

    results = [
        await execute_media_node_run(session, node_run_id=run.id, store=store) for run in runs
    ]
    await session.commit()

    # Both episodes submitted the same frozen reference image to the Provider.
    assert len(submitted) == 2
    sent_references: list[bytes] = []
    for request in submitted:
        payload = json.loads(request.content)
        assert payload["model"] == IMAGE_MODEL_ID
        data_uri = payload["extra_body"]["image"][0]
        assert data_uri.startswith(DATA_URI_PREFIX)
        sent_references.append(base64.b64decode(data_uri[len(DATA_URI_PREFIX) :]))
    assert sent_references[0] == sent_references[1] == shared_png

    # Each episode keeps its own keyframe; the shared asset is still one version.
    assert results[0].artifact_id != results[1].artifact_id
    produced_hashes: list[str] = []
    for result in results:
        produced = await session.get(Artifact, result.artifact_id)
        assert produced is not None
        assert produced.mime_type == "image/png"
        assert produced.content_hash != artifact.content_hash
        produced_hashes.append(produced.content_hash)
    assert len(set(produced_hashes)) == 2

    operations = list(
        await session.scalars(
            select(ProviderOperation).where(
                ProviderOperation.node_run_id.in_([run.id for run in runs])
            )
        )
    )
    assert len(operations) == 2
    assert {operation.status for operation in operations} == {"succeeded"}

    await session.refresh(asset)
    formal_versions = await session.scalar(
        select(func.count())
        .select_from(AssetVersion)
        .where(AssetVersion.asset_id == asset.id, AssetVersion.status == "formal")
    )
    assert formal_versions == 1
    assert asset.current_version_id == version.id
    assert asset.version == 1
