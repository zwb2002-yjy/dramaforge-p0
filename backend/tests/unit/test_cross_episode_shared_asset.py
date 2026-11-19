"""Cross-episode shared asset resolves identically in both shot plans (I8b)."""

from __future__ import annotations

from uuid import uuid4

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
from app.execution.models import Artifact
from app.production.models import ShotReferenceBinding
from app.production.workbench_execution import WorkbenchExecutionInput, WorkbenchExecutionService
from app.providers.models import ProviderModelBinding
from model_infra_fixture import seed_model_infra
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _two_episode_shots(
    session: AsyncSession,
) -> tuple[Project, User, list[Shot], ProviderModelBinding]:
    suffix = uuid4().hex[:8]
    user = User(email=f"share-{suffix}@example.com", display_name="S", password_hash="x")
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
    await seed_model_infra(session, project=project, user=user)
    image_binding = await session.scalar(
        select(ProviderModelBinding).where(
            ProviderModelBinding.workspace_id == workspace.id,
            ProviderModelBinding.media_type == "image",
        )
    )
    assert image_binding is not None
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
            visual_description="",
            dialogue="",
            duration_seconds=5,
            image_prompt="frame",
            video_prompt="motion",
        )
        session.add(shot)
        shots.append(shot)
    await session.flush()
    return project, user, shots, image_binding


def _input(project: Project, shot: Shot, binding_id, reference) -> WorkbenchExecutionInput:
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
async def test_same_asset_reference_plans_in_both_episodes(session: AsyncSession) -> None:
    project, user, shots, image_binding = await _two_episode_shots(session)
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
        created_by=user.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="c" * 64,
        mime_type="image/png",
        byte_size=1,
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
    bindings: list[ShotReferenceBinding] = []
    for shot in shots:
        binding = ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot.id,
            stage="image",
            asset_id=asset.id,
            resolution_mode="current_formal",
            purpose="identity",
            label="Hero",
            metadata_json={},
            created_by=user.id,
        )
        session.add(binding)
        bindings.append(binding)
    await session.flush()

    service = WorkbenchExecutionService(session, user_id=user.id)
    planned_artifacts: list[str] = []
    for shot, binding in zip(shots, bindings, strict=True):
        reference = ShotReferenceIntent(
            binding_id=binding.id,
            purpose="identity",
            asset_version_id=version.id,
            artifact_id=artifact.id,
            mime_type="image/png",
        )
        plan = await service.build_plan(
            project=project,
            execution_input=_input(project, shot, image_binding.id, reference),
        )
        assert len(plan.planned_references) == 1
        planned = plan.planned_references[0]
        assert planned.artifact_id == artifact.id
        assert planned.asset_version_id == version.id
        planned_artifacts.append(str(planned.artifact_id))
    assert planned_artifacts == [str(artifact.id), str(artifact.id)]


@pytest.mark.asyncio
async def test_shared_asset_is_frozen_into_both_dispatches(
    session: AsyncSession, monkeypatch
) -> None:
    """Both episode dispatches freeze the same reference artifact identity."""
    from app.production.workbench_execution import CompilePreview
    from app.storage.minio_store import reset_object_store_for_tests

    project, user, shots, image_binding = await _two_episode_shots(session)
    store = reset_object_store_for_tests()
    stored = await store.put_bytes(
        object_key=f"obj/{uuid4().hex}",
        data=b"\x89PNG\r\n\x1a\nshared-reference",
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
        created_by=user.id,
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
    bindings: list[ShotReferenceBinding] = []
    for shot in shots:
        binding = ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot.id,
            stage="image",
            asset_id=asset.id,
            resolution_mode="current_formal",
            purpose="identity",
            label="Hero",
            metadata_json={},
            created_by=user.id,
        )
        session.add(binding)
        bindings.append(binding)
    await session.flush()

    async def fake_contract_preview(**kwargs: object) -> CompilePreview:
        return CompilePreview(
            readiness="contract_validated",
            prompt_hash="a" * 64,
            semantic_hash="b" * 64,
            manifest_hash="c" * 64,
            reference_ids=[artifact.id],
            effective_options={},
            wire_fingerprint="d" * 64,
        )

    monkeypatch.setattr(
        "app.production.workbench_execution.preview_compile", fake_contract_preview
    )
    service = WorkbenchExecutionService(session, user_id=user.id)
    runs = []
    for shot, binding in zip(shots, bindings, strict=True):
        reference = ShotReferenceIntent(
            binding_id=binding.id,
            purpose="identity",
            asset_version_id=version.id,
            artifact_id=artifact.id,
            mime_type="image/png",
        )
        run = await service.create_and_dispatch(
            project=project,
            execution_input=_input(project, shot, image_binding.id, reference),
            confirmed_compiler_wire_fingerprint="d" * 64,
        )
        runs.append(run)
    await session.commit()
    assert len(runs) == 2
    for run in runs:
        snapshot = run.input_snapshot or {}
        assert snapshot["references"][0]["artifact_id"] == str(artifact.id)
        assert snapshot["references"][0]["asset_version_id"] == str(version.id)
        assert snapshot["shot_id"] in {str(shot.id) for shot in shots}
    assert runs[0].graph_version_id != runs[1].graph_version_id