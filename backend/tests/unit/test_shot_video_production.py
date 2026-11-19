"""The video stage submits the shot's formal keyframe as its first frame (I8b)."""

from __future__ import annotations

import base64
import json

import pytest
from app.config import clear_settings_cache
from app.contracts.shot_reference import ShotReferenceIntent
from app.execution.models import Artifact, ProviderOperation
from app.execution.product_path import execute_media_node_run
from app.production.formal_selection import set_formal_keyframe
from app.production.models import ShotReferenceBinding
from app.shared.errors import ProviderTaskPendingError
from app.storage.minio_store import reset_object_store_for_tests
from cryptography.fernet import Fernet
from production_harness import (
    VIDEO_MODEL_ID,
    agnes_image_binding,
    agnes_video_binding,
    configure_image_default,
    configure_video_default,
    dispatch_keyframe,
    dispatch_stage,
    install_fake_agnes,
    seed_project,
    shared_asset_reference,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.formal_fixture import approve_candidate


@pytest.mark.asyncio
async def test_video_stage_submits_the_formal_keyframe(session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    # The 2.5 frame contract delivers references as short-lived public URLs.
    monkeypatch.setenv("REFERENCE_PUBLIC_BASE_URL", "https://media.example")
    clear_settings_cache()

    store = reset_object_store_for_tests()
    video_requests = []
    install_fake_agnes(monkeypatch, colors=["green"], video_requests=video_requests)
    project, owner, shots = await seed_project(session, work_type="single_comic")
    shot = shots[0]
    image_binding = await agnes_image_binding(session, project=project, owner=owner)
    video_binding = await agnes_video_binding(
        session, project=project, owner=owner, connection_id=image_binding.connection_id
    )
    await configure_image_default(session, project=project, owner=owner, binding=image_binding)
    await configure_video_default(session, project=project, owner=owner, binding=video_binding)
    _, version, artifact, _shared_png = await shared_asset_reference(
        session, project=project, owner=owner, shots=[shot], store=store
    )
    await session.commit()

    # The video stage only accepts a formal keyframe, so produce one first.
    shot_binding = (
        await session.scalars(
            select(ShotReferenceBinding).where(ShotReferenceBinding.shot_id == shot.id)
        )
    ).one()
    _, keyframe_run = await dispatch_keyframe(
        session,
        project=project,
        shot=shot,
        binding_id=image_binding.id,
        user_id=owner.id,
        reference=ShotReferenceIntent(
            binding_id=shot_binding.id,
            purpose="identity",
            asset_version_id=version.id,
            artifact_id=artifact.id,
            mime_type="image/png",
        ),
    )
    await session.commit()
    keyframe_result = await execute_media_node_run(
        session, node_run_id=keyframe_run.id, store=store
    )
    keyframe = await session.get(Artifact, keyframe_result.artifact_id)
    assert keyframe is not None
    await approve_candidate(session, shot=shot, artifact=keyframe, actor_id=owner.id)
    await set_formal_keyframe(
        session, project_id=project.id, shot_id=shot.id, artifact_id=keyframe.id
    )
    await session.commit()

    plan, video_run = await dispatch_stage(
        session,
        project=project,
        shot=shot,
        binding_id=video_binding.id,
        user_id=owner.id,
        stage="video",
        # The frame contract needs the approved formal keyframe as first_frame.
        reference=ShotReferenceIntent(
            purpose="first_frame",
            artifact_id=keyframe.id,
            mime_type="image/png",
        ),
    )
    assert plan.stage == "video"
    assert plan.input_contract_id == "frame"
    await session.commit()

    with pytest.raises(ProviderTaskPendingError):
        await execute_media_node_run(session, node_run_id=video_run.id, store=store)
    await session.commit()

    # Exactly one paid create, and it carries a signed reference to the keyframe.
    creates = [
        request
        for request in video_requests
        if request.method == "POST" and request.url.path == "/v1/videos"
    ]
    assert len(creates) == 1
    payload = json.loads(creates[0].content)
    assert payload["model"] == VIDEO_MODEL_ID
    serialized = json.dumps(payload)
    assert "https://media.example/" in serialized
    keyframe_bytes = await store.get_bytes(object_key=keyframe.object_key)
    assert base64.b64encode(keyframe_bytes).decode() not in serialized

    # The remote task is observed, not re-created, and nothing is final yet.
    operations = list(
        await session.scalars(
            select(ProviderOperation).where(ProviderOperation.node_run_id == video_run.id)
        )
    )
    assert len(operations) == 1
    assert operations[0].operation_kind == "video.generate"
    assert operations[0].provider_operation_id == "vid-1"
    await session.refresh(shot)
    assert shot.formal_video_artifact_id is None
