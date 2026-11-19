"""Shared fixtures for project production-segment tests (I8b).

These helpers build the smallest real-Provider-shaped project: a work type with
its episode plan, one configured image model with a frozen credential revision,
and (when a test needs a reference) one formal Asset version.  They are test
support, not product code; nothing here fabricates a Provider response outside
an injected transport.
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from uuid import uuid4

import httpx
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
from sqlalchemy.ext.asyncio import AsyncSession

IMAGE_MODEL_ID = "agnes-image-2.5-flash"
DATA_URI_PREFIX = "data:image/png;base64,"

WORK_TYPE_EPISODES: dict[str, tuple[int | None, int]] = {
    # work_type -> (planned_episode_count, episodes to create)
    "single_comic": (1, 1),
    "serial_comic": (2, 2),
    "animation_promo": (None, 1),
}


def png(color: str = "red") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1024, 1024), color).save(buffer, "PNG")
    return buffer.getvalue()


def submission_reference(request: httpx.Request) -> bytes:
    """Decode the reference image the Worker embedded in an Agnes image body."""
    payload = json.loads(request.content)
    data_uri = payload["extra_body"]["image"][0]
    assert data_uri.startswith(DATA_URI_PREFIX)
    return base64.b64decode(data_uri[len(DATA_URI_PREFIX) :])


def install_fake_agnes(monkeypatch, *, colors: list[str]) -> list[httpx.Request]:
    """Serve discovery plus one distinct generated image per submission.

    Byte-identical outputs across shots are rejected by the artifact
    independence guard, so each submission answers with its own colour.
    """
    from app.execution import media_io

    submitted: list[httpx.Request] = []
    generated = {f"/{index + 1}.png": png(color) for index, color in enumerate(colors)}

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
    return submitted


async def seed_project(
    session: AsyncSession,
    *,
    work_type: str,
    shots_per_episode: int = 1,
) -> tuple[Project, User, list[Shot]]:
    """One project of the given work type with its structural minimum."""
    planned, episodes = WORK_TYPE_EPISODES[work_type]
    suffix = uuid4().hex[:8]
    user = User(email=f"prod-{suffix}@example.com", display_name="P", password_hash="x")
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
        work_type=work_type,
        planned_episode_count=planned,
    )
    session.add(project)
    await session.flush()
    shots: list[Shot] = []
    for episode_number in range(1, episodes + 1):
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
        for shot_number in range(1, shots_per_episode + 1):
            shot = Shot(
                project_id=project.id,
                scene_id=scene.id,
                shot_number=shot_number,
                sort_order=shot_number,
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


async def agnes_image_binding(session: AsyncSession, *, project: Project, owner: User):
    """One Agnes image connection with a decryptable frozen credential revision."""
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_sync import sync_model_catalog
    from app.providers.connection_service import ProviderConnectionService
    from app.providers.models import ProviderConnection, ProviderConnectionRevision
    from app.providers.workspace_credentials import configured_byok_keyring
    from app.security.credentials import store_credential
    from sqlalchemy import select

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


async def configure_image_default(
    session: AsyncSession, *, project: Project, owner: User, binding
) -> None:
    """Point the project's effective profile at the verified image binding.

    A project-level production run resolves the model from its media defaults;
    without this the Workbench correctly reports every shot as blocked.  The
    project-level profile row is created here because a workspace-level row must
    keep its media slots empty.
    """
    from app.providers.model_profiles.orm import ProductionModelProfile
    from app.providers.model_profiles.service import ProductionModelProfileService

    profile = await ProductionModelProfileService(session).get_project_profile(
        project_id=project.id
    )
    slot_binding = {
        "visual.keyframe": {
            "slot": "visual.keyframe",
            "model_id": IMAGE_MODEL_ID,
            "native_options": {},
            "enabled": True,
        }
    }
    if profile is None:
        profile = ProductionModelProfile(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name="default",
            version=1,
            is_default=True,
            bindings=slot_binding,
            created_by=owner.id,
            updated_by=owner.id,
        )
        session.add(profile)
        await session.flush()
    profile.bindings = {**profile.bindings, **slot_binding}
    profile.image_model_binding_id = binding.id
    await session.flush()


async def shared_asset_reference(
    session: AsyncSession,
    *,
    project: Project,
    owner: User,
    shots: list[Shot],
    store,
) -> tuple[Asset, AssetVersion, object, bytes]:
    """One character asset, one formal version, one reference artifact.

    Every given shot gets its own binding to the same version, so sharing is a
    property of the reference identity rather than of a copied asset.
    """
    from app.execution.models import Artifact

    shared_png = png("red")
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


def keyframe_input(
    project: Project,
    *,
    shot: Shot,
    binding_id,
    reference: ShotReferenceIntent | None = None,
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
        references=[reference] if reference is not None else [],
    )


async def dispatch_keyframe(
    session: AsyncSession,
    *,
    project: Project,
    shot: Shot,
    binding_id,
    user_id,
    reference: ShotReferenceIntent | None = None,
):
    """Plan, prove the compiler wire, then queue one keyframe NodeRun."""
    workbench = WorkbenchExecutionService(session, user_id=user_id)
    command = keyframe_input(project, shot=shot, binding_id=binding_id, reference=reference)
    plan = await workbench.build_plan(project=project, execution_input=command)
    proof = await workbench.preview_compiler_contract(project=project, plan=plan)
    assert proof is not None and proof.wire_fingerprint is not None
    run = await workbench.create_and_dispatch(
        project=project,
        execution_input=command,
        prepared_plan=plan,
        confirmed_compiler_wire_fingerprint=proof.wire_fingerprint,
    )
    return plan, run
