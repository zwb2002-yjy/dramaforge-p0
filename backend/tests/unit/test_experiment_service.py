"""P5-03 Experiment creation service tests (03 §47)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.production.experiment_service import (
    ExperimentCreateInput,
    ExperimentService,
    recompile_controls_for_model,
)
from app.production.models import (
    ShotExperiment,
    ShotReferenceBinding,
)
from app.providers.capabilities import Capability
from app.providers.manifest import (
    CapabilitySpec,
    InputSlotSpec,
    ModelManifest,
    SubmissionSemantics,
)
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import select
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


async def _seed(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"exp-{uuid4().hex}@example.com",
        display_name="Exp",
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
    return project, user


async def _shot(
    session: AsyncSession,
    *,
    project: Project,
    scene_id=None,
    shot_number: int = 1,
) -> Shot:
    shot = Shot(
        project_id=project.id,
        scene_id=scene_id or uuid4(),
        shot_number=shot_number,
        version=3,
        visual_description="Shot",
        director_state={"camera": "static"},
        image_prompt="keyframe prompt",
        video_prompt="video prompt",
    )
    session.add(shot)
    await session.flush()
    return shot


@pytest.mark.asyncio
async def test_create_experiment_single_shot_snapshots_inputs(session: AsyncSession) -> None:
    project, user = await _seed(session)
    shot = await _shot(session, project=project)
    session.add(
        ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot.id,
            purpose="identity",
            asset_id=uuid4(),
            sort_order=1,
            created_by=user.id,
        )
    )
    await session.flush()

    experiment = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(
            name="A/B",
            shot_ids=[shot.id],
            model_overrides={"video.shot": "agnes/model-b"},
            idempotency_key=f"exp-{uuid4().hex}",
        ),
    )
    shot_exp = (
        await session.execute(
            select(ShotExperiment).where(ShotExperiment.production_experiment_id == experiment.id)
        )
    ).scalars().one()
    assert shot_exp.source_shot_version == 3
    assert shot_exp.director_state == {"camera": "static"}
    assert shot_exp.prompts["image_prompt"] == "keyframe prompt"
    assert shot_exp.model_overrides["video.shot"] == "agnes/model-b"
    assert len(shot_exp.references) == 1
    assert shot_exp.references[0]["purpose"] == "identity"
    # formal shot untouched
    await session.refresh(shot)
    assert shot.version == 3


@pytest.mark.asyncio
async def test_create_experiment_scene_creates_all_shots(session: AsyncSession) -> None:
    project, user = await _seed(session)
    scene_id = uuid4()
    s1 = await _shot(session, project=project, scene_id=scene_id, shot_number=1)
    s2 = await _shot(session, project=project, scene_id=scene_id, shot_number=2)
    experiment = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(
            name="Scene A/B",
            scene_id=scene_id,
            idempotency_key=f"exp-{uuid4().hex}",
        ),
    )
    rows = (
        await session.execute(
            select(ShotExperiment).where(ShotExperiment.production_experiment_id == experiment.id)
        )
    ).scalars().all()
    assert {row.shot_id for row in rows} == {s1.id, s2.id}


@pytest.mark.asyncio
async def test_create_experiment_idempotent_and_requires_shots(session: AsyncSession) -> None:
    project, user = await _seed(session)
    shot = await _shot(session, project=project)
    key = f"exp-{uuid4().hex}"
    first = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(name="a", shot_ids=[shot.id], idempotency_key=key),
    )
    second = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(name="b", shot_ids=[shot.id], idempotency_key=key),
    )
    assert first.id == second.id
    with pytest.raises(ValidationAppError, match="at least one shot"):
        await ExperimentService(session).create_experiment(
            project=project,
            actor=user,
            experiment_input=ExperimentCreateInput(
                name="c", shot_ids=[], idempotency_key=f"exp-{uuid4().hex}"
            ),
        )



def _model_b_manifest() -> ModelManifest:
    return ModelManifest(
        manifest_version="1",
        id="agnes/video-model-b",
        provider_id="agnes",
        model_name="video-model-b",
        display_name="Video Model B",
        capability_specs={
            Capability.VIDEO_IMAGE_TO_VIDEO: CapabilitySpec(
                capability=Capability.VIDEO_IMAGE_TO_VIDEO,
                transport_profile_id="t1",
                input_slots={
                    "first_frame": InputSlotSpec(minimum=0, maximum=1, media_types=["image/*"]),
                    "reference_image": InputSlotSpec(minimum=0, maximum=4, media_types=["image/*"]),
                },
                common_options={
                    "duration_seconds": {"type": "integer", "ui_component": "number"}
                },
            )
        },
        execution_mode="async_poll",
        submission_semantics=SubmissionSemantics(),
    )


def test_recompile_drops_model_a_native_options_and_preserves_semantic() -> None:
    manifest = _model_b_manifest()
    result = recompile_controls_for_model(
        manifest=manifest,
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[],
        common_controls={
            "aspect_ratio": "9:16",
            "duration_seconds": 10,
            "seed": 7,
            "seed_mode": "fixed",
        },
        mode_id="explicit_binding",
    )
    controls = result["common_controls"]
    assert controls.get("aspect_ratio") == "9:16"
    assert controls.get("duration_seconds") == 10
    assert "seed" not in controls
    assert "seed_mode" not in controls
    assert result["dropped_native_options"] == ["seed", "seed_mode"]


def test_recompile_surfaces_unsupported_reference() -> None:
    manifest = _model_b_manifest()
    result = recompile_controls_for_model(
        manifest=manifest,
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        references=[{"purpose": "action", "artifact_id": str(uuid4()), "mime_type": "video/mp4"}],
        common_controls={},
        mode_id="explicit_binding",
    )
    assert result["unsupported_controls"]



async def _seed_with_model_b(session: AsyncSession) -> tuple[Project, User, str]:
    from datetime import date

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
    from app.providers.models import ProviderConnection, ProviderModelBinding

    user = User(
        email=f"swap-{uuid4().hex}@example.com",
        display_name="Swap",
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
        workspace_id=workspace.id,
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
    binding = ProviderModelBinding(
        workspace_id=workspace.id,
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
    shot = Shot(
        project_id=project.id,
        scene_id=uuid4(),
        shot_number=1,
        version=1,
        visual_description="Swap shot",
        director_state={"camera": "static"},
        image_prompt="keyframe",
        video_prompt="video",
    )
    session.add(shot)
    await session.flush()
    return project, user, str(shot.id)


@pytest.mark.asyncio
async def test_create_model_swap_experiment_recompiles(session: AsyncSession) -> None:
    project, user, shot_id = await _seed_with_model_b(session)
    experiment = await ExperimentService(session).create_model_swap_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(
            name="Swap to B",
            shot_ids=[UUID(shot_id)],
            model_overrides={"video.shot": "agnes-video-v2.0"},
            idempotency_key=f"swap-{uuid4().hex}",
        ),
    )
    shot_exp = (
        await session.execute(
            select(ShotExperiment).where(
                ShotExperiment.production_experiment_id == experiment.id
            )
        )
    ).scalars().one()
    assert shot_exp.model_overrides["video.shot"] == "agnes-video-v2.0"
    assert "model_swap_recompile" in (shot_exp.comparison or {})
    assert isinstance(shot_exp.comparison["model_swap_recompile"], dict)
