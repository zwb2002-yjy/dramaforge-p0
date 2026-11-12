"""Agent media diagnostics reuse real compilers without I/O or production writes."""

from uuid import uuid4

import httpx
import pytest
from app.api.director_model_tools import ApiDirectorModelTools
from app.assets.models import Scene, Shot
from app.contracts.director_model_tools import (
    ModelCapabilitiesInput,
    ModelCapabilitiesRead,
    ModelCompilePreviewInput,
    ModelToolScope,
)
from app.director.agent_tools import ToolContext, ToolExecutor
from app.providers.models import ProjectProviderBinding, ProviderConnectionRevision
from app.shared.errors import ConflictError, NotFoundError
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.unit.test_workbench_execution import _seed, _seed_image_shot


async def _fixture(session):
    project, video_binding, actor = await _seed(session)
    shot, artifact, binding = await _seed_image_shot(
        session,
        project=project,
        user=actor,
        connection_id=video_binding.connection_id,
    )
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="keyframe",
            model_binding_id=binding.id,
            updated_by=actor.id,
        )
    )
    await session.commit()
    scope = ModelToolScope(
        actor_id=actor.id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        scope_type="project",
        scope_entity_id=project.id,
    )
    port = ApiDirectorModelTools(async_sessionmaker(bind=session.bind, expire_on_commit=False))
    return port, scope, shot, binding, project, actor


def _preview(shot, report, **changes):
    return ModelCompilePreviewInput.model_validate(
        {
            "shot_id": shot.id,
            "expected_shot_version": shot.version,
            "stage": "image_keyframe",
            "mode_id": "text_to_image",
            "prompt": shot.image_prompt,
            "requested_binding_id": report.binding_id,
            "expected_identity_hash": report.identity_hash,
            "expected_manifest_hash": report.manifest_hash,
            **changes,
        }
    )


async def test_inspection_and_preview_do_not_read_credentials_call_network_or_write(
    session,
    monkeypatch,
):
    port, scope, shot, binding, _, _ = await _fixture(session)

    async def forbidden(*args, **kwargs):
        pytest.fail("read-only media inspection must not use network or credentials")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr("app.security.credentials.read_credential_by_id", forbidden)
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        report = await port.inspect(
            scope=scope,
            request=ModelCapabilitiesInput(
                stage="image_keyframe",
                mode_id="text_to_image",
            ),
        )
        first = await port.preview(scope=scope, request=_preview(shot, report))
        second = await port.preview(scope=scope, request=_preview(shot, report))
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
    assert report.binding_id == binding.id
    assert report.binding_status == "RESOLVED"
    assert len(report.identity_hash) == len(report.manifest_hash) == 64
    assert report.account_verified is report.transport_verified is False
    assert first.readiness == "contract_validated"
    assert first.plan_fingerprint == second.plan_fingerprint
    assert first.snapshot_hash == second.snapshot_hash
    assert first.identity_hash == report.identity_hash
    assert first.wire_fingerprint and len(first.wire_fingerprint) == 64
    assert first.observed_versions[f"shot:{shot.id}"] == shot.version
    assert "NO_EXECUTION_AUTHORIZATION" in first.warnings
    assert "MEDIA_BYTES_NOT_VERIFIED" in first.warnings
    assert "PLACEHOLDER_TRANSPORT_NOT_VERIFIED" in first.warnings
    assert "character walks into frame" not in first.model_dump_json()
    assert "credential" not in first.model_dump_json()
    assert "redacted_wire" not in first.model_dump_json()
    assert "https://api.agnes" not in first.model_dump_json()
    assert all(
        sql.lstrip().split(" ", 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        for sql in statements
    )
    assert all("encrypted_provider_credentials" not in sql for sql in statements)


async def test_executor_wires_capability_hashes_into_read_only_compile_preview(
    session,
    monkeypatch,
):
    _, scope, shot, binding, project, _ = await _fixture(session)
    factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)
    executor = ToolExecutor(factory, model_tools=ApiDirectorModelTools(factory))
    context = ToolContext(
        **scope.model_dump(exclude={"expected_versions"}),
        turn_id=uuid4(),
        thread_id=uuid4(),
        expected_versions={
            f"project:{project.id}": project.version,
            f"shot:{shot.id}": shot.version,
        },
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("model tools must not use network or credentials through the executor")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr("app.security.credentials.read_credential_by_id", forbidden)
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        inspected = await executor.execute(
            name="model_capabilities",
            arguments={"stage": "image_keyframe", "mode_id": "text_to_image"},
            call_id="inspect-media-1",
            context=context,
        )
        assert inspected.ok, inspected.error
        report = ModelCapabilitiesRead.model_validate(inspected.data)
        previewed = await executor.execute(
            name="model_compile_preview",
            arguments=_preview(shot, report).model_dump(mode="json"),
            call_id="compile-media-1",
            context=context,
        )
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", capture)

    assert inspected.call_id == "inspect-media-1"
    assert inspected.observed_versions == {f"project:{project.id}": project.version}
    assert inspected.provenance["tool"] == "model_capabilities"
    assert report.binding_id == binding.id
    assert previewed.ok, previewed.error
    assert previewed.call_id == "compile-media-1"
    assert previewed.observed_versions == context.expected_versions
    assert previewed.provenance["tool"] == "model_compile_preview"
    assert previewed.data["identity_hash"] == report.identity_hash
    assert previewed.data["manifest_hash"] == report.manifest_hash
    assert previewed.data["readiness"] == "contract_validated"
    assert previewed.data["account_verified"] is False
    assert previewed.data["transport_verified"] is False
    assert len(inspected.result_hash) == len(previewed.result_hash) == 64
    assert all(
        sql.lstrip().split(" ", 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        for sql in statements
    )
    assert all("encrypted_provider_credentials" not in sql for sql in statements)


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_shot_version": 99},
        {"expected_manifest_hash": "0" * 64},
        {"expected_identity_hash": "0" * 64},
        {"requested_binding_id": uuid4()},
    ],
)
async def test_preview_rejects_stale_or_different_selected_identity(session, changes):
    port, scope, shot, _, _, _ = await _fixture(session)
    report = await port.inspect(
        scope=scope,
        request=ModelCapabilitiesInput(
            stage="image_keyframe",
            mode_id="text_to_image",
        ),
    )
    with pytest.raises(ConflictError) as error:
        await port.preview(scope=scope, request=_preview(shot, report, **changes))
    assert error.value.details["code"] == "CONTEXT_STALE"


async def test_connection_revision_change_invalidates_preview_identity(session):
    port, scope, shot, binding, _, _ = await _fixture(session)
    report = await port.inspect(
        scope=scope,
        request=ModelCapabilitiesInput(
            stage="image_keyframe",
            mode_id="text_to_image",
        ),
    )
    original = await session.scalar(
        select(ProviderConnectionRevision).where(
            ProviderConnectionRevision.connection_id == binding.connection_id,
        )
    )
    session.add(
        ProviderConnectionRevision(
            connection_id=binding.connection_id,
            revision_no=original.revision_no + 1,
            provider_type=original.provider_type,
            protocol_profile=original.protocol_profile,
            base_url=original.base_url,
            credential_revision_id=original.credential_revision_id,
        )
    )
    await session.commit()
    with pytest.raises(ConflictError):
        await port.preview(scope=scope, request=_preview(shot, report))


async def test_tools_enforce_narrow_scope_and_observed_versions(session):
    port, scope, shot, _, project, actor = await _fixture(session)
    original_scene = await session.get(Scene, shot.scene_id)
    other_scene = Scene(
        episode_id=original_scene.episode_id,
        scene_number=2,
        location_name="Other studio",
        time_of_day="day",
        synopsis="",
    )
    session.add(other_scene)
    await session.flush()
    other_shot = Shot(
        project_id=project.id,
        scene_id=other_scene.id,
        shot_number=1,
        version=1,
        visual_description="Other",
        image_prompt="Other shot",
    )
    session.add(other_shot)
    await session.commit()
    report = await port.inspect(
        scope=scope,
        request=ModelCapabilitiesInput(
            stage="image_keyframe",
            mode_id="text_to_image",
        ),
    )
    for narrow_scope in (
        scope.model_copy(update={"scope_type": "scene", "scope_entity_id": other_scene.id}),
        scope.model_copy(update={"scope_type": "shot", "scope_entity_id": other_shot.id}),
        scope.model_copy(update={"actor_id": uuid4()}),
    ):
        with pytest.raises(NotFoundError):
            await port.preview(scope=narrow_scope, request=_preview(shot, report))
    with pytest.raises(ConflictError):
        await port.inspect(
            scope=scope.model_copy(update={"expected_versions": {f"project:{project.id}": 99}}),
            request=ModelCapabilitiesInput(stage="image_keyframe"),
        )


def test_model_tool_input_has_no_execution_credential_or_text_registry_surface():
    for value in (
        {"stage": "planning.script"},
        {"stage": "image_keyframe", "model_id": "litellm/private"},
        {"stage": "image_keyframe", "api_key": "secret"},
    ):
        with pytest.raises(ValidationError):
            ModelCapabilitiesInput.model_validate(value)
    base = {
        "shot_id": uuid4(),
        "expected_shot_version": 1,
        "stage": "image_keyframe",
        "mode_id": "text_to_image",
        "prompt": "saved",
        "requested_binding_id": uuid4(),
        "expected_identity_hash": "a" * 64,
        "expected_manifest_hash": "b" * 64,
    }
    for injected in ({"accept_approximations": True}, {"api_key": "secret"}, {"execute": True}):
        with pytest.raises(ValidationError):
            ModelCompilePreviewInput.model_validate({**base, **injected})
