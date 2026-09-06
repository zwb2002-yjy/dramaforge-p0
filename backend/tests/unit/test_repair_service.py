"""P6-04/05/06 Manual repair service tests (03 §56-58)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.delivery.models import ReviewAnnotation
from app.production.repair_service import RepairService
from app.shared.base import Base
from app.shared.errors import ValidationAppError
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
        email=f"repair-{uuid4().hex}@example.com",
        display_name="Repair",
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
    from app.execution.models import Artifact

    formal_keyframe = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="stored",
        object_key=f"obj/{uuid4().hex}",
        content_hash="f" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(formal_keyframe)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=uuid4(),
        shot_number=1,
        version=1,
        visual_description="Repair shot",
        image_prompt="keyframe prompt",
        video_prompt="video prompt",
        formal_keyframe_artifact_id=formal_keyframe.id,
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


@pytest.mark.asyncio
async def test_repair_plan_with_video_range_suggests_regenerate(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    session.add(
        ReviewAnnotation(
            project_id=project.id,
            shot_id=shot.id,
            created_by=user.id,
            time_start=2.3,
            time_end=3.1,
            note="人物漂移",
            severity="warning",
            status="open",
        )
    )
    await session.flush()
    plan = await RepairService(session).build_repair_plan(project=project, shot_id=shot.id)
    assert plan.suggested_option == "regenerate_keyframe_then_video"
    assert plan.affected_nodes == ["keyframe", "video"]
    assert plan.annotation_count == 1


@pytest.mark.asyncio
async def test_repair_plan_region_suggests_rerun_video(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    session.add(
        ReviewAnnotation(
            project_id=project.id,
            shot_id=shot.id,
            created_by=user.id,
            x=0.2, y=0.3, width=0.4, height=0.2,
            note="色偏",
            severity="warning",
            status="open",
        )
    )
    await session.flush()
    plan = await RepairService(session).build_repair_plan(project=project, shot_id=shot.id)
    assert plan.suggested_option == "rerun_video"
    assert plan.affected_nodes == ["video"]
    assert "formal_keyframe" in plan.retained_assets




async def _seed_model_infra(session: AsyncSession, *, project: Project, user: User) -> None:
    """Seed catalog entry + connection + revision + binding + profile so the
    workbench resolver returns RESOLVED for video.shot / visual.keyframe."""
    from datetime import date

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
    from app.providers.model_profiles.orm import ProductionModelProfile
    from app.providers.models import (
        ProviderConnection,
        ProviderConnectionRevision,
        ProviderModelBinding,
    )

    manifest = next(item for item in SEED_MANIFESTS if item["model_id"] == "agnes-video-v2.0")
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
        model_revision="v1",
        display_name="Agnes Video",
        media_kind="video",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(manifest),
    )
    session.add(entry)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=project.workspace_id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()
    revision = ProviderConnectionRevision(
        connection_id=connection.id,
        revision_no=1,
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        base_url="https://api.agnes-ai.cn",
        credential_revision_id=connection.credential_id,
    )
    session.add(revision)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=project.workspace_id,
        connection_id=connection.id,
        media_type="video",
        model_id="agnes-video-v2.0",
        purpose="video",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-video-v2.0",
        invoke_model_value="agnes-video-v2.0",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    image_manifest = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "agnes-image-2.1-flash"
    )
    image_entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-image-2.1-flash",
        model_revision="v1",
        display_name="Agnes Image",
        media_kind="image",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=image_manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(image_manifest),
    )
    session.add(image_entry)
    await session.flush()
    image_binding = ProviderModelBinding(
        workspace_id=project.workspace_id,
        connection_id=connection.id,
        media_type="image",
        model_id="agnes-image-2.1-flash",
        purpose="keyframe",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=image_entry.id,
        capability_manifest_hash=image_entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-image-2.1-flash",
        invoke_model_value="agnes-image-2.1-flash",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(image_binding)
    await session.flush()
    bindings = {
        "video.shot": {
            "slot": "video.shot",
            "model_id": "agnes-video-v2.0",
            "native_options": {},
            "enabled": True,
        },
        "visual.keyframe": {
            "slot": "visual.keyframe",
            "model_id": "agnes-image-2.1-flash",
            "native_options": {},
            "enabled": True,
        },
    }
    profile = ProductionModelProfile(
        workspace_id=project.workspace_id,
        project_id=project.id,
        name="default",
        version=1,
        is_default=True,
        bindings=bindings,
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(profile)
    await session.flush()


@pytest.mark.asyncio
async def test_execute_repair_rerun_video_dispatches_queued_run(session: AsyncSession) -> None:

    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    run = await RepairService(session).execute_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_option="rerun_video",
        idempotency_key="repair-key-1",
    )
    assert run.status == "queued"
    assert run.idempotency_key.startswith("workbench:video:repair:repair-key-1")
    snapshot = run.input_snapshot or {}
    assert snapshot["workbench_plan"]["semantic_intent"].get("repair") == "rerun_video"


@pytest.mark.asyncio
async def test_execute_repair_regenerate_dispatches_keyframe(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    await _seed_model_infra(session, project=project, user=user)
    run = await RepairService(session).execute_repair(
        project=project,
        user=user,
        shot_id=shot.id,
        repair_option="regenerate_keyframe_then_video",
        idempotency_key="repair-key-2",
    )
    snapshot = run.input_snapshot or {}
    assert snapshot["workbench_plan"]["stage"] == "image_keyframe"
    assert snapshot["workbench_plan"]["semantic_intent"].get("repair") == (
        "regenerate_keyframe_then_video"
    )


@pytest.mark.asyncio
async def test_execute_repair_rerun_video_requires_formal_keyframe(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    shot.formal_keyframe_artifact_id = None
    await session.flush()
    with pytest.raises(ValidationAppError, match="formal keyframe"):
        await RepairService(session).execute_repair(
            project=project,
            user=user,
            shot_id=shot.id,
            repair_option="rerun_video",
            idempotency_key="repair-key-3",
        )
