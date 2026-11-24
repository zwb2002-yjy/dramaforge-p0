"""The video stage runs from the shot's approved formal keyframe to a formal video (I8b)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from app.config import clear_settings_cache
from app.contracts.shot_reference import ShotReferenceIntent
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.execution.product_path import execute_media_node_run
from app.production.formal_selection import set_formal_keyframe, set_formal_video
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


@dataclass
class ReadyShot:
    project: object
    owner: object
    shot: object
    keyframe: Artifact
    store: object
    image_binding: object
    video_binding: object
    video_requests: list


async def _shot_with_formal_keyframe(
    session: AsyncSession, monkeypatch, *, video_states: list[dict] | None = None
) -> ReadyShot:
    """Produce one approved formal keyframe through the real production chain."""
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    # The 2.5 frame contract delivers references as short-lived public URLs.
    monkeypatch.setenv("REFERENCE_PUBLIC_BASE_URL", "https://media.example")
    clear_settings_cache()

    store = reset_object_store_for_tests()
    video_requests: list = []
    install_fake_agnes(
        monkeypatch,
        colors=["green"],
        video_requests=video_requests,
        video_states=video_states,
    )
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
    return ReadyShot(
        project=project,
        owner=owner,
        shot=shot,
        keyframe=keyframe,
        store=store,
        image_binding=image_binding,
        video_binding=video_binding,
        video_requests=video_requests,
    )


async def _dispatch_video(session: AsyncSession, ready: ReadyShot):
    plan, run = await dispatch_stage(
        session,
        project=ready.project,
        shot=ready.shot,
        binding_id=ready.video_binding.id,
        user_id=ready.owner.id,
        stage="video",
        # The frame contract needs the approved formal keyframe as first_frame.
        reference=ShotReferenceIntent(
            purpose="first_frame",
            artifact_id=ready.keyframe.id,
            mime_type="image/png",
        ),
    )
    await session.commit()
    return plan, run


def _creates(requests: list) -> list:
    return [
        request
        for request in requests
        if request.method == "POST" and request.url.path == "/v1/videos"
    ]


@pytest.mark.asyncio
async def test_video_stage_submits_the_formal_keyframe(session: AsyncSession, monkeypatch) -> None:
    ready = await _shot_with_formal_keyframe(session, monkeypatch)
    plan, run = await _dispatch_video(session, ready)
    assert plan.stage == "video"
    assert plan.input_contract_id == "frame"

    with pytest.raises(ProviderTaskPendingError):
        await execute_media_node_run(session, node_run_id=run.id, store=ready.store)
    await session.commit()

    # Exactly one paid create, and it carries a signed reference to the keyframe.
    creates = _creates(ready.video_requests)
    assert len(creates) == 1
    payload = json.loads(creates[0].content)
    assert payload["model"] == VIDEO_MODEL_ID
    serialized = json.dumps(payload)
    assert "https://media.example/" in serialized
    keyframe_bytes = await ready.store.get_bytes(object_key=ready.keyframe.object_key)
    assert base64.b64encode(keyframe_bytes).decode() not in serialized

    # The remote task is observed, not re-created, and nothing is final yet.
    operations = list(
        await session.scalars(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    )
    assert len(operations) == 1
    assert operations[0].operation_kind == "video.generate"
    assert operations[0].provider_operation_id == "vid-1"
    await session.refresh(ready.shot)
    assert ready.shot.formal_video_artifact_id is None


@pytest.mark.asyncio
async def test_video_stage_completes_to_a_formal_video(session: AsyncSession, monkeypatch) -> None:
    ready = await _shot_with_formal_keyframe(
        session,
        monkeypatch,
        # The first attempt only defers; the first observation happens next call.
        video_states=[
            {"status": "succeeded", "url": "https://media.example/v.mp4", "progress": 1.0}
        ],
    )
    _, run = await _dispatch_video(session, ready)

    with pytest.raises(ProviderTaskPendingError):
        await execute_media_node_run(session, node_run_id=run.id, store=ready.store)
    await session.commit()

    # The next observation is allowed once the deferred poll becomes due.
    stored_run = await session.get(NodeRun, run.id)
    assert stored_run is not None
    stored_run.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()

    result = await execute_media_node_run(session, node_run_id=run.id, store=ready.store)
    await session.commit()
    assert result.artifact_id is not None
    video = await session.get(Artifact, result.artifact_id)
    assert video is not None
    assert video.mime_type == "video/mp4"
    assert video.produced_by_run_id == run.id

    # One create for the whole task; the completion came from polling.
    assert len(_creates(ready.video_requests)) == 1
    polls = [
        request
        for request in ready.video_requests
        if request.method == "GET" and request.url.path == "/agnesapi"
    ]
    assert len(polls) == 1

    await approve_candidate(
        session, shot=ready.shot, artifact=video, actor_id=ready.owner.id, video=True
    )
    await set_formal_video(
        session, project_id=ready.project.id, shot_id=ready.shot.id, artifact_id=video.id
    )
    await session.commit()

    await session.refresh(ready.shot)
    assert ready.shot.formal_video_artifact_id == video.id
