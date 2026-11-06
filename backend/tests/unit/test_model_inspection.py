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


async def test_explicit_model_query_uses_only_the_projects_workspace_binding_registry(session):
    project, binding, owner = await _seed(session)
    _other_project, other_binding, _ = await _seed(session)
    await session.commit()
    service = ModelInspectionService(session, actor=owner)
    result = await service.get_model_capabilities(
        project_id=project.id,
        model_id=f"binding:{binding.id}",
    )
    assert result.report.model_id == f"binding:{binding.id}"
    with pytest.raises(NotFoundError):
        await service.get_model_capabilities(
            project_id=project.id,
            model_id=f"binding:{other_binding.id}",
        )


async def test_generation_options_expose_profile_defaults_and_compiler_owned_editability(session):
    from app.providers.model_profiles.orm import ProductionModelProfile
    from app.providers.model_profiles.slots import ModelSlot
    from tests.unit.test_workbench_execution import _video_manifest_with_contract

    project, binding, owner = await _seed(
        session, manifest_override=_video_manifest_with_contract()
    )
    session.add(
        ProductionModelProfile(
            workspace_id=project.workspace_id,
            project_id=project.id,
            name="model defaults",
            version=1,
            is_default=False,
            bindings={
                ModelSlot.VIDEO_SHOT.value: {
                    "slot": ModelSlot.VIDEO_SHOT.value,
                    "model_id": f"binding:{binding.id}",
                    "native_options": {"resolution": "720p"},
                    "enabled": True,
                }
            },
            created_by=owner.id,
            updated_by=owner.id,
        )
    )
    await session.commit()
    result = await ModelInspectionService(session, actor=owner).get_model_capabilities(
        project_id=project.id,
        stage="video",
        mode_id="first_frame",
    )
    assert result.resolution.source == "project_profile"
    assert result.connection_label == "Agnes"
    assert result.generation_options["resolution"].editable
    assert result.generation_options["resolution"].inherited_value == "720p"
    assert result.generation_options["resolution"].inherited_source == "project_profile"
    assert not result.generation_options["fps"].editable
    assert result.generation_options["fps"].reason == "compiler_unavailable"


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
    monkeypatch: pytest.MonkeyPatch,
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
    assert report.report.model_id == "agnes/unit-agnes-video"
    from uuid import uuid4

    import httpx
    from app.config import get_settings
    from app.providers.litellm_gateway.management import GatewayManagementClient, GatewayModelWrite
    from app.providers.litellm_gateway.management_service import GatewayModelService
    from cryptography.fernet import Fernet
    from test_gateway_model_management import ProxyFixture

    cfg = get_settings().model_copy(
        update={
            "litellm_gateway_url": "http://proxy.internal:4000",
            "litellm_api_key": "synthetic-data",
            "litellm_model_admin_key": "restricted-model-admin",
            "byok_fernet_key": Fernet.generate_key().decode(),
            "byok_keyring": "",
        }
    )
    manager = GatewayModelService(
        session,
        settings=cfg,
        client=GatewayManagementClient(cfg, transport=httpx.MockTransport(ProxyFixture().handle)),
    )
    connection = await manager.register(
        workspace_id=project.workspace_id,
        actor=actor,
        body=GatewayModelWrite(
            request_id=uuid4(),
            display_name="Inspection text",
            base_url="https://physical.example/v1",
            model_id="inspected-chat",
            api_key="synthetic-upstream",
        ),
    )
    monkeypatch.setattr("app.providers.workspace_credentials.get_settings", lambda: cfg)
    text = await service.get_model_capabilities(
        project_id=project.id,
        slot=ModelSlot.PLANNING_SCRIPT,
    )
    assert text.selection == "text_slot"
    assert text.report.model_id == f"litellm/{connection.id}/{connection.gateway_ref['alias']}"
    assert text.report.controls["tool_calling"] == "unknown"
