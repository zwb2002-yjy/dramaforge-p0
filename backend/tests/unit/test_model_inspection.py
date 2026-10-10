"""Authorized model queries and dry-runs share the existing workbench services."""

from uuid import UUID

import pytest
from app.production.model_inspection import ModelInspectionService
from app.providers.compile_preview import CompilePreview
from app.shared.errors import ForbiddenError, NotFoundError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.test_workbench_execution import (
    _input,
    _seed,
    _seed_image_shot,
    session,
)

__all__ = ["session"]


@pytest.mark.parametrize("mode_id", ["explicit_binding", "text_to_image"])
async def test_preview_is_authorized_deterministic_and_read_only(
    session: AsyncSession, mode_id: str
) -> None:
    project, binding, actor = await _seed(session)
    shot, _artifact, image_binding = await _seed_image_shot(
        session,
        project=project,
        user=actor,
        connection_id=binding.connection_id,
    )
    await session.commit()
    writes: list[str] = []

    def record(_connection: object, _cursor: object, statement: str, *_: object) -> None:
        if statement.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    assert session.bind is not None
    event.listen(session.bind.sync_engine, "before_cursor_execute", record)
    service = ModelInspectionService(session, actor=actor)
    request = _input(
        project_id=project.id,
        shot_id=shot.id,
        requested_binding_id=image_binding.id,
        stage="image_keyframe",
        mode_id=mode_id,
        expected_shot_version=shot.version,
    )
    first = await service.preview_generation_compile(project_id=project.id, request=request)
    second = await service.preview_generation_compile(project_id=project.id, request=request)
    assert isinstance(first.compilation, CompilePreview)
    assert first.compilation.readiness == "contract_validated"
    assert first.compilation.effective_options["aspect_ratio"] == "9:16"
    assert first.snapshot_hash == second.snapshot_hash
    assert writes == []
    assert "credential_revision_id" not in first.model_dump_json()
    assert "character walks into frame" not in first.model_dump_json()


async def test_snapshot_refuses_run_outside_authorized_project(session: AsyncSession) -> None:
    project, _binding, actor = await _seed(session)
    await session.commit()
    with pytest.raises(NotFoundError):
        await ModelInspectionService(session, actor=actor).get_generation_snapshot(
            project_id=project.id,
            shot_id=UUID(int=1),
            run_id=UUID(int=2),
        )


async def test_actual_snapshot_reports_plan_compilation_and_observed_artifact(
    session: AsyncSession,
) -> None:
    from app.execution.models import ProviderOperation
    from app.production.workbench_execution import WorkbenchExecutionService

    project, binding, actor = await _seed(session)
    shot, _artifact, image_binding = await _seed_image_shot(
        session,
        project=project,
        user=actor,
        connection_id=binding.connection_id,
    )
    request = _input(
        project_id=project.id,
        shot_id=shot.id,
        requested_binding_id=image_binding.id,
        stage="image_keyframe",
        expected_shot_version=1,
    )
    service = WorkbenchExecutionService(session, user_id=actor.id)
    plan = await service.build_plan(project=project, execution_input=request)
    run = await service.create_and_dispatch(
        project=project,
        execution_input=request,
        prepared_plan=plan,
        idempotency_key_override="snapshot-test",
    )
    session.add(
        ProviderOperation(
            node_run_id=run.id,
            operation_kind="image.generate",
            actual_provider="agnes",
            actual_model="agnes-image-2.1-flash",
            request_fingerprint="a" * 64,
            status="succeeded",
            request_summary={
                "effective_request_redacted": {
                    "common_options": {"size": "1K", "aspect_ratio": "9:16"},
                    "prompt": "SECRET",
                    "url": "https://secret.invalid/?token=secret",
                }
            },
            response_summary={"api_key": "SECRET"},
        )
    )
    run.result_artifact_id = _artifact.id
    _artifact.width, _artifact.height = 736, 1312
    await session.commit()
    snapshot = await ModelInspectionService(session, actor=actor).get_generation_snapshot(
        project_id=project.id, shot_id=shot.id, run_id=run.id
    )
    assert snapshot.planned_model_id == "agnes/agnes-image-2.1-flash"
    assert snapshot.compiled_models == ["agnes-image-2.1-flash"]
    assert snapshot.compiled_request_hashes == ["a" * 64]
    assert len(snapshot.operation_ids) == 1
    assert snapshot.compiled_options == [{"size": "1K", "aspect_ratio": "9:16"}]
    assert snapshot.observed_output["width"] == 736
    assert "SECRET" not in snapshot.model_dump_json()
    assert "https://secret" not in snapshot.model_dump_json()


async def test_query_and_preview_reject_cross_project_or_stale_inputs(
    session: AsyncSession,
) -> None:
    from app.shared.errors import ValidationAppError

    project, binding, actor = await _seed(session)
    other, _, _ = await _seed(session)
    shot, _, image_binding = await _seed_image_shot(
        session, project=project, user=actor, connection_id=binding.connection_id
    )
    await session.commit()
    service = ModelInspectionService(session, actor=actor)
    with pytest.raises(ForbiddenError):
        await service.get_model_capabilities(project_id=other.id, model_id="minimax/image-01")
    request = _input(
        project_id=project.id,
        shot_id=shot.id,
        stage="image_keyframe",
        requested_binding_id=image_binding.id,
        expected_shot_version=99,
    )
    with pytest.raises(ValidationAppError, match="version"):
        await service.preview_generation_compile(project_id=project.id, request=request)
    request = request.model_copy(update={"expected_shot_version": 1, "accept_approximations": True})
    with pytest.raises(ValidationAppError, match="approximations"):
        await service.preview_generation_compile(project_id=project.id, request=request)


async def test_query_current_media_binding_and_text_slot_are_distinct(
    session: AsyncSession,
) -> None:
    from app.providers.model_profiles.slots import ModelSlot
    from app.providers.models import ProjectProviderBinding

    project, binding, actor = await _seed(session)
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            updated_by=actor.id,
        )
    )
    await session.commit()
    service = ModelInspectionService(session, actor=actor)
    report = await service.get_model_capabilities(project_id=project.id, stage="video")
    assert report.selection == "current_binding"
    assert report.binding_id == binding.id
    assert report.report.model_id == "agnes/agnes-video-v2.0"
    text = await service.get_model_capabilities(
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
    )
    assert text.selection == "text_slot"
    assert text.report.model_id.startswith("litellm/")
    assert text.report.controls["tool_calling"] == "unknown"
