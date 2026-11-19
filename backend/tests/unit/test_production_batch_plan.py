"""A project-level production batch preview reports plans and blockers only (I8b)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.config import clear_settings_cache
from app.execution.models import Artifact
from app.production.batch_plan import ProductionBatchPlanService
from app.shared.errors import ValidationAppError
from app.storage.minio_store import reset_object_store_for_tests
from cryptography.fernet import Fernet
from production_harness import agnes_image_binding, configure_image_default, seed_project
from sqlalchemy.ext.asyncio import AsyncSession


def _install_keys(monkeypatch) -> None:
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    clear_settings_cache()
    reset_object_store_for_tests()


@pytest.mark.parametrize("work_type", ["single_comic", "serial_comic", "animation_promo"])
@pytest.mark.asyncio
async def test_batch_preview_plans_every_shot_of_each_work_type(
    session: AsyncSession, monkeypatch, work_type: str
) -> None:
    _install_keys(monkeypatch)
    project, owner, shots = await seed_project(session, work_type=work_type)
    binding = await agnes_image_binding(session, project=project, owner=owner)
    await configure_image_default(session, project=project, owner=owner, binding=binding)
    await session.commit()

    preview = await ProductionBatchPlanService(session, user_id=owner.id).preview(
        project=project, stage="image_keyframe"
    )
    assert len(preview.items) == len(shots)
    assert preview.planned_count == len(shots)
    assert preview.blocked_count == 0
    assert preview.formal_count == 0
    assert preview.max_operations == len(shots)
    assert {item.stage for item in preview.items} == {"image_keyframe"}
    assert all(item.plan_fingerprint for item in preview.items)
    # Results follow episode/scene/shot order, not insertion order.
    assert [item.shot_id for item in preview.items] == [shot.id for shot in shots]


@pytest.mark.asyncio
async def test_batch_preview_is_stable_and_shrinks_when_a_shot_is_formal(
    session: AsyncSession, monkeypatch
) -> None:
    _install_keys(monkeypatch)
    project, owner, shots = await seed_project(session, work_type="serial_comic")
    binding = await agnes_image_binding(session, project=project, owner=owner)
    await configure_image_default(session, project=project, owner=owner, binding=binding)
    await session.commit()

    service = ProductionBatchPlanService(session, user_id=owner.id)
    first = await service.preview(project=project, stage="image_keyframe")
    second = await service.preview(project=project, stage="image_keyframe")
    assert first.batch_fingerprint == second.batch_fingerprint

    # A finished shot leaves the paid set: it is reported as formal, not planned.
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="a" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(artifact)
    await session.flush()
    shots[0].formal_keyframe_artifact_id = artifact.id
    await session.flush()

    third = await service.preview(project=project, stage="image_keyframe")
    assert third.formal_count == 1
    assert third.planned_count == len(shots) - 1
    assert third.batch_fingerprint != first.batch_fingerprint


@pytest.mark.asyncio
async def test_batch_preview_reports_blockers_instead_of_failing(
    session: AsyncSession, monkeypatch
) -> None:
    _install_keys(monkeypatch)
    project, owner, shots = await seed_project(session, work_type="single_comic")
    await session.commit()

    # No image model is configured at all: every shot is blocked, none raises.
    preview = await ProductionBatchPlanService(session, user_id=owner.id).preview(
        project=project, stage="image_keyframe"
    )
    assert preview.planned_count == 0
    assert preview.blocked_count == len(shots)
    assert preview.max_operations == 0
    assert preview.items[0].blockers
    assert preview.items[0].plan_fingerprint is None

    # Video without a formal keyframe is reported per shot, not as a failure.
    video = await ProductionBatchPlanService(session, user_id=owner.id).preview(
        project=project, stage="video"
    )
    assert video.blocked_count == len(shots)
    assert video.items[0].stage == "video"


@pytest.mark.asyncio
async def test_batch_preview_rejects_other_stages_and_foreign_shots(
    session: AsyncSession,
) -> None:
    project, owner, _shots = await seed_project(session, work_type="single_comic")
    service = ProductionBatchPlanService(session, user_id=owner.id)
    with pytest.raises(ValidationAppError) as unsupported:
        await service.preview(project=project, stage="image_edit")  # type: ignore[arg-type]
    assert unsupported.value.details["code"] == "BATCH_STAGE_UNSUPPORTED"

    _other_project, _other_owner, other_shots = await seed_project(
        session, work_type="single_comic"
    )
    with pytest.raises(ValidationAppError) as foreign:
        await service.preview(project=project, stage="image_keyframe", shot_ids=[other_shots[0].id])
    assert foreign.value.details["code"] == "BATCH_SHOT_UNKNOWN"


@pytest.mark.asyncio
async def test_batch_preview_can_be_scoped_to_given_shots(
    session: AsyncSession, monkeypatch
) -> None:
    _install_keys(monkeypatch)
    project, owner, shots = await seed_project(
        session, work_type="serial_comic", shots_per_episode=2
    )
    binding = await agnes_image_binding(session, project=project, owner=owner)
    await configure_image_default(session, project=project, owner=owner, binding=binding)
    await session.commit()

    preview = await ProductionBatchPlanService(session, user_id=owner.id).preview(
        project=project, stage="image_keyframe", shot_ids=[shots[1].id]
    )
    assert [item.shot_id for item in preview.items] == [shots[1].id]
    assert preview.max_operations == 1
