"""One shared asset reaches both episodes' Provider submissions (I8b).

The earlier slices prove the shared reference is planned and frozen the same way
for both episodes.  This one follows the same frozen reference through the real
Worker media path (``execute_media_node_run``) into the Provider request, so the
sharing is verified at the paid boundary rather than only in a snapshot: both
episodes submit the identical asset bytes, each keeps its own generated
keyframe, and the Asset keeps exactly one formal version.
"""

from __future__ import annotations

import pytest
from app.assets.models import AssetVersion
from app.config import clear_settings_cache
from app.contracts.shot_reference import ShotReferenceIntent
from app.execution.models import Artifact, ProviderOperation
from app.execution.product_path import execute_media_node_run
from app.production.models import ShotReferenceBinding
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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_shared_asset_reaches_both_episode_provider_submissions(
    session: AsyncSession, monkeypatch
) -> None:
    # One frozen bearer revision per workspace, decryptable in this process only.
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    clear_settings_cache()

    store = reset_object_store_for_tests()
    submitted = install_fake_agnes(monkeypatch, colors=["green", "blue"])
    project, owner, shots = await seed_project(session, work_type="serial_comic")
    binding = await agnes_image_binding(session, project=project, owner=owner)
    asset, version, artifact, shared_png = await shared_asset_reference(
        session, project=project, owner=owner, shots=shots, store=store
    )
    await session.commit()

    planned_artifacts: list[str] = []
    runs = []
    for shot in shots:
        shot_binding = (
            await session.scalars(
                select(ShotReferenceBinding).where(ShotReferenceBinding.shot_id == shot.id)
            )
        ).one()
        plan, run = await dispatch_keyframe(
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
        assert len(plan.planned_references) == 1
        assert plan.planned_references[0].role == "reference_image"
        planned_artifacts.append(str(plan.planned_references[0].artifact_id))
        runs.append(run)
    await session.commit()
    assert planned_artifacts == [str(artifact.id), str(artifact.id)]

    results = [
        await execute_media_node_run(session, node_run_id=run.id, store=store) for run in runs
    ]
    await session.commit()

    # Both episodes submitted the same frozen reference image to the Provider.
    assert len(submitted) == 2
    sent_references = [submission_reference(request) for request in submitted]
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
