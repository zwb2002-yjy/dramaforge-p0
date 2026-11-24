"""All three work types reach formal media through the production segment (I8b).

I8b-01 acceptance is "T10/T15 production segment to formal media, with at least
two episodes sharing".  The per-shot mechanism already has focused coverage; this
walks each work type through its own structure (single episode, two episodes,
promo) to a formal keyframe, and re-reads the project readiness to show the
production segment finished rather than only that a request was queued.
"""

from __future__ import annotations

import pytest
from app.config import clear_settings_cache
from app.contracts.shot_reference import ShotReferenceIntent
from app.execution.models import Artifact
from app.execution.product_path import execute_media_node_run
from app.production.formal_selection import set_formal_keyframe
from app.production.models import ShotReferenceBinding
from app.production.readiness import read_production_readiness
from app.storage.minio_store import reset_object_store_for_tests
from cryptography.fernet import Fernet
from production_harness import (
    agnes_image_binding,
    dispatch_keyframe,
    install_fake_agnes,
    seed_project,
    shared_asset_reference,
    submission_reference,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.formal_fixture import approve_candidate

COLORS = ["green", "blue", "purple", "orange"]


@pytest.mark.parametrize("work_type", ["single_comic", "serial_comic", "animation_promo"])
@pytest.mark.asyncio
async def test_each_work_type_reaches_formal_keyframes(
    session: AsyncSession, monkeypatch, work_type: str
) -> None:
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    clear_settings_cache()

    store = reset_object_store_for_tests()
    project, owner, shots = await seed_project(session, work_type=work_type)
    submitted = install_fake_agnes(monkeypatch, colors=COLORS[: len(shots)])
    binding = await agnes_image_binding(session, project=project, owner=owner)
    _, version, artifact, shared_png = await shared_asset_reference(
        session, project=project, owner=owner, shots=shots, store=store
    )
    await session.commit()

    # Every shot of every episode is produced with the same shared reference.
    formal_artifacts: list[str] = []
    for shot in shots:
        shot_binding = (
            await session.scalars(
                select(ShotReferenceBinding).where(ShotReferenceBinding.shot_id == shot.id)
            )
        ).one()
        _, run = await dispatch_keyframe(
            session,
            project=project,
            shot=shot,
            binding_id=binding.id,
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
        result = await execute_media_node_run(session, node_run_id=run.id, store=store)
        produced = await session.get(Artifact, result.artifact_id)
        assert produced is not None
        await approve_candidate(session, shot=shot, artifact=produced, actor_id=owner.id)
        await set_formal_keyframe(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=produced.id,
        )
        await session.commit()
        formal_artifacts.append(str(produced.id))

    # One Provider submission per shot, all carrying the same shared reference.
    assert len(submitted) == len(shots)
    assert {submission_reference(request) for request in submitted} == {shared_png}

    readiness = await read_production_readiness(session, project_id=project.id)
    assert readiness.work_type == work_type
    assert readiness.shot_count == len(shots)
    assert readiness.formal_keyframe_count == len(shots)
    assert readiness.episode_count == (2 if work_type == "serial_comic" else 1)
    assert len(set(formal_artifacts)) == len(shots)

    # The formal pointer is a real fact, not a queued request.
    for shot in shots:
        await session.refresh(shot)
        assert shot.formal_keyframe_artifact_id is not None


@pytest.mark.asyncio
async def test_serial_comic_produces_both_episodes_with_one_shared_asset(
    session: AsyncSession, monkeypatch
) -> None:
    """The two-episode case keeps every shot of both episodes on one asset."""
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    clear_settings_cache()

    store = reset_object_store_for_tests()
    project, owner, shots = await seed_project(
        session, work_type="serial_comic", shots_per_episode=2
    )
    submitted = install_fake_agnes(monkeypatch, colors=COLORS)
    binding = await agnes_image_binding(session, project=project, owner=owner)
    asset, version, artifact, shared_png = await shared_asset_reference(
        session, project=project, owner=owner, shots=shots, store=store
    )
    await session.commit()

    for shot in shots:
        shot_binding = (
            await session.scalars(
                select(ShotReferenceBinding).where(ShotReferenceBinding.shot_id == shot.id)
            )
        ).one()
        _, run = await dispatch_keyframe(
            session,
            project=project,
            shot=shot,
            binding_id=binding.id,
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
        result = await execute_media_node_run(session, node_run_id=run.id, store=store)
        await session.commit()
        produced = await session.get(Artifact, result.artifact_id)
        assert produced is not None
        await approve_candidate(session, shot=shot, artifact=produced, actor_id=owner.id)
        await set_formal_keyframe(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=produced.id,
        )
        await session.commit()

    assert len(submitted) == 4
    assert {submission_reference(request) for request in submitted} == {shared_png}

    readiness = await read_production_readiness(session, project_id=project.id)
    assert readiness.episode_count == 2
    assert readiness.scene_count == 2
    assert readiness.shot_count == 4
    assert readiness.formal_keyframe_count == 4
    assert readiness.shared_asset_count == 1
    assert "cross_episode_sharing" not in readiness.blockers
    await session.refresh(asset)
    assert asset.version == 1
