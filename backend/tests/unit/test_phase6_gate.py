"""Phase 6 Gate tests (03 §59): drift annotation -> repair -> new formal, old in history."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.delivery.models import ReviewAnnotation
from app.execution.models import Artifact
from app.production.repair_service import RepairService
from app.shared.base import Base
from app.shared.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[Project, Shot, User]:
    user = User(
        email=f"gate6-{uuid4().hex}@example.com",
        display_name="Gate6",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        actor=user,
    )
    old_keyframe = Artifact(
        project_id=project.id, artifact_type="image", storage_state="stored",
        object_key=f"obj/{uuid4().hex}", content_hash="a" * 64,
        mime_type="image/png", byte_size=1,
    )
    old_video = Artifact(
        project_id=project.id, artifact_type="video", storage_state="stored",
        object_key=f"obj/{uuid4().hex}", content_hash="b" * 64,
        mime_type="video/mp4", byte_size=2,
    )
    session.add_all([old_keyframe, old_video])
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=uuid4(),
        shot_number=1,
        version=1,
        visual_description="Gate6 shot",
        image_prompt="keyframe prompt",
        video_prompt="video prompt",
        formal_keyframe_artifact_id=old_keyframe.id,
        formal_video_artifact_id=old_video.id,
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


async def _seed_model_infra(session: AsyncSession, *, project: Project, user: User) -> None:
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
    from app.providers.model_profiles.orm import ProductionModelProfile
    from app.providers.models import (
        ProviderConnection,
        ProviderConnectionRevision,
        ProviderModelBinding,
    )

    video_manifest = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "agnes-video-v2.0"
    )
    image_manifest = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "agnes-image-2.1-flash"
    )
    entry = ModelCatalogEntry(
        provider_type="agnes", protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0", model_revision="v1",
        display_name="Agnes Video", media_kind="video", lifecycle="active",
        catalog_source="official_static", capability_manifest_json=video_manifest,
        option_schema_json={}, documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(video_manifest),
    )
    session.add(entry)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=project.workspace_id, provider_type="agnes", display_name="Agnes",
        base_url="https://api.agnes-ai.cn", protocol_profile="agnes_cn_v1",
        credential_id=uuid4(), credential_revision=1, enabled=True,
        verification_status="verified", created_by=user.id, updated_by=user.id,
    )
    session.add(connection)
    await session.flush()
    session.add(
        ProviderConnectionRevision(
            connection_id=connection.id, revision_no=1, provider_type="agnes",
            protocol_profile="agnes_cn_v1", base_url="https://api.agnes-ai.cn",
            credential_revision_id=connection.credential_id,
        )
    )
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=project.workspace_id, connection_id=connection.id,
        media_type="video", model_id="agnes-video-v2.0", purpose="video",
        enabled=True, documented=True, contract_tested=True, account_verified=True,
        quality_gated=True, catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model", remote_resource_id="agnes-video-v2.0",
        invoke_model_value="agnes-video-v2.0", created_by=user.id, updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    image_entry = ModelCatalogEntry(
        provider_type="agnes", protocol_profile="agnes_cn_v1",
        model_id="agnes-image-2.1-flash", model_revision="v1",
        display_name="Agnes Image", media_kind="image", lifecycle="active",
        catalog_source="official_static", capability_manifest_json=image_manifest,
        option_schema_json={}, documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(image_manifest),
    )
    session.add(image_entry)
    await session.flush()
    image_binding = ProviderModelBinding(
        workspace_id=project.workspace_id, connection_id=connection.id,
        media_type="image", model_id="agnes-image-2.1-flash", purpose="keyframe",
        enabled=True, documented=True, contract_tested=True, account_verified=True,
        quality_gated=True, catalog_entry_id=image_entry.id,
        capability_manifest_hash=image_entry.contract_manifest_hash,
        remote_resource_kind="model", remote_resource_id="agnes-image-2.1-flash",
        invoke_model_value="agnes-image-2.1-flash", created_by=user.id, updated_by=user.id,
    )
    session.add(image_binding)
    await session.flush()
    session.add(
        ProductionModelProfile(
            workspace_id=project.workspace_id, project_id=project.id, name="default",
            version=1, is_default=True,
            bindings={
                "video.shot": {"slot": "video.shot", "model_id": "agnes-video-v2.0",
                               "native_options": {}, "enabled": True},
                "visual.keyframe": {"slot": "visual.keyframe",
                                    "model_id": "agnes-image-2.1-flash",
                                    "native_options": {}, "enabled": True},
            },
            created_by=user.id, updated_by=user.id,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_phase6_gate_drift_repair_keeps_old_formal_in_history(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    old_keyframe_id = shot.formal_keyframe_artifact_id
    old_video_id = shot.formal_video_artifact_id

    # 1) mark 2.3-3.1s drift
    session.add(
        ReviewAnnotation(
            project_id=project.id, shot_id=shot.id, created_by=user.id,
            time_start=2.3, time_end=3.1, note="人物漂移", severity="warning",
            status="open",
        )
    )
    await session.flush()

    # 2) repair plan
    repair = RepairService(session)
    plan = await repair.build_repair_plan(project=project, shot_id=shot.id)
    assert plan.suggested_option == "regenerate_keyframe_then_video"
    assert plan.affected_nodes == ["keyframe", "video"]

    # 3) regenerate keyframe candidate (new keyframe NodeRun queued)
    keyframe_run = await repair.execute_repair(
        project=project, user=user, shot_id=shot.id,
        repair_option="regenerate_keyframe_then_video",
        idempotency_key="gate6-kf",
    )
    assert keyframe_run.status == "queued"
    assert keyframe_run.input_snapshot["workbench_plan"]["stage"] == "image_keyframe"

    # 4) user confirms a new keyframe candidate (new formal keyframe artifact)
    new_keyframe = Artifact(
        project_id=project.id, artifact_type="image", storage_state="stored",
        object_key=f"obj/{uuid4().hex}", content_hash="c" * 64,
        mime_type="image/png", byte_size=1,
    )
    session.add(new_keyframe)
    await session.flush()
    shot.formal_keyframe_artifact_id = new_keyframe.id
    shot.formal_video_artifact_id = None  # old video pending regeneration
    shot.version += 1
    await session.flush()

    # 5) rerun video on the new keyframe
    video_run = await repair.execute_repair(
        project=project, user=user, shot_id=shot.id,
        repair_option="rerun_video",
        idempotency_key="gate6-video",
    )
    assert video_run.status == "queued"
    assert video_run.input_snapshot["workbench_plan"]["stage"] == "video"

    # 6) old formal results remain in history (artifacts still referenced)
    old_kf_row = await session.get(Artifact, old_keyframe_id)
    old_video_row = await session.get(Artifact, old_video_id)
    assert old_kf_row is not None
    assert old_video_row is not None
    # the shot advanced to the new keyframe while the old video artifact persists
    assert shot.formal_keyframe_artifact_id == new_keyframe.id
    assert shot.version >= 2
