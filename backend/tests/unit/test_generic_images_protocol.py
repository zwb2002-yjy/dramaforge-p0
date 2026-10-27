"""One conservative Images contract accepts different configured services without model branches."""

from __future__ import annotations

import base64
import json
from io import BytesIO

import httpx
import pytest
from app.config import Settings
from app.providers.catalog_loader import ModelCatalogLoader
from app.providers.intents import ImageGenerationIntent, ModelSelectionIntent
from app.providers.manifest import ModelCapabilityManifest
from app.providers.openai_compatible_media import (
    OPENAI_IMAGES_PROFILE,
    OpenAICompatibleImageCompiler,
    OpenAICompatibleMediaRuntime,
)
from PIL import Image
from test_model_profiles_api import api as api
from tests.unit.test_workbench_execution import session as session


def png(color="red"):
    buffer = BytesIO()
    Image.new("RGB", (1024, 1024), color).save(buffer, "PNG")
    return buffer.getvalue()


def manifest():
    raw = next(
        item.as_dict()
        for item in ModelCatalogLoader().load()
        if item.identity[1] == OPENAI_IMAGES_PROFILE
    )
    return ModelCapabilityManifest.model_validate(raw)


def intent(**kwargs):
    return ImageGenerationIntent(
        prompt="synthetic image", selection=ModelSelectionIntent(mode="explicit_binding"), **kwargs
    )


@pytest.mark.parametrize(
    "path, expected",
    [
        ("", "/v1"),
        ("/v1/", "/v1"),
        ("/gateway/team/v1/images/generations", "/gateway/team/v1"),
        ("/api/v3", "/api/v3"),
    ],
)
def test_images_endpoint_normalization_preserves_explicit_prefix(path, expected):
    from app.providers.openai_compatible_media import normalize_images_base_url

    normalized = normalize_images_base_url("https://service.test" + path)
    assert normalized == "https://service.test" + expected
    assert normalize_images_base_url(normalized) == normalized


@pytest.mark.parametrize("representation", ["b64_json", "binary", "url"])
@pytest.mark.parametrize("auth_mode", ["none", "bearer"])
async def test_synchronous_images_are_bytes_without_remote_task_or_poll(representation, auth_mode):
    sent = []
    content = png()

    def receive(request):
        sent.append(request)
        assert request.headers.get("Authorization") == (
            "Bearer fixture-key" if auth_mode == "bearer" else None
        )
        if request.method == "GET":
            assert request.url.path == "/result.png"
            return httpx.Response(200, content=content, headers={"Content-Type": "image/png"})
        assert json.loads(request.content) == {
            "model": "configured-id",
            "prompt": "synthetic image",
            "size": "1024x1024",
            "n": 1,
        }
        if representation == "binary":
            return httpx.Response(200, content=content, headers={"Content-Type": "image/png"})
        value = (
            base64.b64encode(content).decode()
            if representation == "b64_json"
            else "https://service.test/result.png"
        )
        return httpx.Response(200, json={"data": [{representation: value}]})

    compiled = await OpenAICompatibleImageCompiler(OPENAI_IMAGES_PROFILE).compile(
        intent(), manifest(), [], invoke_model_value="configured-id"
    )
    runtime = OpenAICompatibleMediaRuntime(
        protocol_profile=OPENAI_IMAGES_PROFILE,
        settings=Settings(
            _env_file=None,
            openai_compatible_media_enabled=True,
            openai_compatible_media_auth_mode=auth_mode,
            openai_compatible_media_api_key="fixture-key" if auth_mode == "bearer" else "",
            openai_compatible_media_base_url="https://service.test/v1",
        ),
        transport=httpx.MockTransport(receive),
    )
    result = await runtime.submit_image(compiled)
    assert result.status == "succeeded"
    assert result.remote_task_id is result.resume_token is result.artifact_uri is None
    assert result.artifact_bytes == content
    assert "artifact_bytes" not in result.model_dump()
    assert [r.method for r in sent] == (["POST", "GET"] if representation == "url" else ["POST"])


@pytest.mark.parametrize("scheme, port", [("http", 80), ("https", 443)])
@pytest.mark.parametrize("explicit_base", [True, False])
async def test_result_url_default_port_is_same_origin(scheme, port, explicit_base):
    from app.providers.image_results import image_result

    base = f"{scheme}://service.test" + (f":{port}" if explicit_base else "")
    target = f"{scheme}://service.test" + ("" if explicit_base else f":{port}")
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(200, content=png(), headers={"Content-Type": "image/png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        response = httpx.Response(200, json={"data": [{"url": target + "/result.png"}]})
        assert await image_result(response, origin=base, client=client, headers={}) == png()
        response = httpx.Response(200, json={"data": [{"url": f"{scheme}://service.test:1234/x"}]})
        with pytest.raises(ValueError, match="origin"):
            await image_result(response, origin=base, client=client, headers={})
    assert len(requests) == 1


@pytest.mark.parametrize(
    "change", [{"size": "512x512"}, {"aspect_ratio": "16:9"}, {"seed": 4}, {"prompt": ""}]
)
async def test_unsupported_parameters_fail_before_any_submit(change):
    value = intent().model_copy(update=change)
    with pytest.raises(ValueError):
        await OpenAICompatibleImageCompiler(OPENAI_IMAGES_PROFILE).compile(
            value, manifest(), [], invoke_model_value="configured-id"
        )


@pytest.mark.parametrize(
    "reply",
    ["external_url", "file_path", "invalid_bytes", "bad_mime", "oversize", "redirect", 429, 503],
)
async def test_protocol_mismatch_and_uncertain_responses_never_retry(reply):
    sent = []

    def receive(request):
        sent.append(request)
        assert request.method == "POST"
        if isinstance(reply, int):
            return httpx.Response(reply)
        if reply == "external_url":
            return httpx.Response(200, json={"data": [{"url": "http://169.254.169.254/metadata"}]})
        if reply == "file_path":
            return httpx.Response(200, json={"file_path": "/private/result.png"})
        if reply == "invalid_bytes":
            return httpx.Response(200, json={"data": [{"b64_json": "not-base64"}]})
        if reply == "bad_mime":
            return httpx.Response(200, content=png(), headers={"Content-Type": "text/html"})
        if reply == "oversize":
            return httpx.Response(
                200,
                content=b"",
                headers={"Content-Type": "image/png", "Content-Length": str(30 * 1024 * 1024)},
            )
        return httpx.Response(307, headers={"Location": "https://service.test/other"})

    compiled = await OpenAICompatibleImageCompiler(OPENAI_IMAGES_PROFILE).compile(
        intent(), manifest(), [], invoke_model_value="configured-id"
    )
    runtime = OpenAICompatibleMediaRuntime(
        protocol_profile=OPENAI_IMAGES_PROFILE,
        settings=Settings(
            _env_file=None,
            openai_compatible_media_enabled=True,
            openai_compatible_media_auth_mode="none",
            openai_compatible_media_base_url="https://service.test/v1",
        ),
        transport=httpx.MockTransport(receive),
    )
    result = await runtime.submit_image(compiled)
    assert result.status == "unknown_submission"
    assert result.artifact_bytes is result.remote_task_id is result.resume_token is None
    assert len(sent) == 1


# The application/API path uses the same immutable catalog entry for two services.
def test_admin_api_registers_two_models_without_catalog_or_code_changes(api, monkeypatch):
    from app.providers.catalog_sync import sync_model_catalog
    from app.security.models import EncryptedProviderCredential
    from sqlalchemy import func, select
    from test_model_profiles_api import _create_project, _csrf, _register, _run_create

    client, factory = api
    workspace = _register(client)
    project = _create_project(client, workspace)

    async def seed():
        async with factory() as session:
            await sync_model_catalog(session, apply=True)
            await session.commit()

    _run_create(seed())
    initial = next(
        p
        for p in client.get("/api/v1/provider-plugins").json()
        if p["protocol_profile"] == OPENAI_IMAGES_PROFILE
    )
    assert len(initial["models"]) == 1
    contract_id = initial["models"][0]["catalog_entry_id"]
    before = list(ModelCatalogLoader().load())
    observed = []

    async def discovery(_client, url, *, headers):
        observed.append((url, headers))
        assert "Authorization" not in headers
        return httpx.Response(200, json={"data": [{"id": "model-alpha"}, {"id": "model-beta"}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", discovery)
    bound = []
    for label in ("alpha", "beta"):
        root = f"/api/v1/workspaces/{workspace}/provider-connections"
        created = client.post(
            root,
            json={
                "display_name": label,
                "provider_type": "openai_compatible_media",
                "protocol_profile": OPENAI_IMAGES_PROFILE,
                "base_url": f"https://{label}.test/v1/images/generations",
                "auth_mode": "none",
            },
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert created.status_code == 201, created.text
        row = created.json()
        assert row["auth_mode"] == "none" and row["credential_configured"] is False
        assert row["base_url"] == f"https://{label}.test/v1"
        # Manual IDs can be saved before discovery, but are visibly unverified.
        manual = client.post(
            root + f"/{row['id']}/model-bindings",
            json={
                "media_type": "image",
                "model_id": f"model-{label}",
                "purpose": "keyframe",
                "capability_contract_id": contract_id,
            },
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert manual.status_code == 201, manual.text
        assert manual.json()["account_verified"] is False
        saved_bindings = client.get(root + f"/{row['id']}/model-bindings")
        assert saved_bindings.status_code == 200, saved_bindings.text
        assert saved_bindings.json()[0]["generation_evidence"] == {
            "connection_revision_id": row["connection_revision_id"],
            "verified": False,
        }
        probed = client.post(
            root + f"/{row['id']}/probes",
            json={"capability": "auth_models"},
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert probed.status_code == 200, probed.text
        assert probed.json()["status"] == "passed"
        selected = client.put(
            f"/api/v1/projects/{project}/provider-bindings/keyframe",
            json={
                "model_binding_id": manual.json()["id"],
                "selection_strategy": "explicit_binding",
            },
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert selected.status_code == 200, selected.text
        bound.append(manual.json()["id"])
    assert len(set(bound)) == 2
    assert before == list(ModelCatalogLoader().load())
    assert {url for url, _ in observed} == {
        "https://alpha.test/v1/models",
        "https://beta.test/v1/models",
    }

    async def count_credentials():
        async with factory() as session:
            return await session.scalar(
                select(func.count()).select_from(EncryptedProviderCredential)
            )

    assert _run_create(count_credentials()) == 0


async def test_two_configured_models_produce_separate_artifacts_through_the_canonical_worker(
    session, monkeypatch
):
    from app.assets.models import Shot
    from app.execution.models import Artifact, ProviderOperation
    from app.execution.product_path import execute_media_node_run
    from app.production.workbench_execution import WorkbenchExecutionService
    from app.providers.catalog_loader import hash_manifest
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_sync import sync_model_catalog
    from app.providers.connection_service import ProviderConnectionService
    from app.storage.minio_store import InMemoryObjectStore
    from sqlalchemy import select
    from tests.unit.test_workbench_execution import _input, _seed, _seed_scene

    project, _old_binding, owner = await _seed(session)
    scene = await _seed_scene(session, project)
    await sync_model_catalog(session, apply=True)
    contract = (
        await session.scalars(
            select(ModelCatalogEntry).where(
                ModelCatalogEntry.protocol_profile == OPENAI_IMAGES_PROFILE
            )
        )
    ).one()
    original_hash = contract.contract_manifest_hash
    sent = []

    def receive(request):
        assert "Authorization" not in request.headers
        if request.method == "GET":
            model_id = "model-alpha" if request.url.host == "alpha.test" else "model-beta"
            return httpx.Response(200, json={"data": [{"id": model_id}]})
        sent.append(request)
        color = "red" if request.url.host == "alpha.test" else "blue"
        return httpx.Response(200, content=png(color), headers={"Content-Type": "image/png"})

    monkeypatch.setattr(
        "app.providers.egress.guarded_provider_transport",
        lambda **kwargs: httpx.MockTransport(receive),
    )
    service = ProviderConnectionService(session)
    store = InMemoryObjectStore()
    artifacts, bindings = [], []
    for index, label in enumerate(("alpha", "beta")):
        connection = await service.create_connection(
            workspace_id=project.workspace_id,
            actor=owner,
            provider_type="openai_compatible_media",
            protocol_profile=OPENAI_IMAGES_PROFILE,
            display_name=label,
            base_url=f"https://{label}.test",
            auth_mode="none",
            api_key=None,
            enabled=True,
        )
        binding = await service.create_model_binding(
            workspace_id=project.workspace_id,
            connection_id=connection.id,
            actor=owner,
            model_id=f"model-{label}",
            media_type="image",
            purpose="keyframe",
            capability_contract_id=contract.id,
            enabled=True,
        )
        await service.probe(
            workspace_id=project.workspace_id,
            connection_id=connection.id,
            actor=owner,
            capability="auth_models",
        )
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=index + 1,
            version=1,
            image_prompt="synthetic image",
            visual_description="synthetic image",
            director_state={
                "generation_settings": {
                    "image_keyframe": {"common_options": {"aspect_ratio": "1:1"}}
                }
            },
        )
        session.add(shot)
        await session.flush()
        command = _input(
            project_id=project.id,
            shot_id=shot.id,
            stage="image_keyframe",
            requested_binding_id=binding.id,
            prompt="synthetic image",
            mode_id="text_to_image",
            expected_shot_version=shot.version,
        )
        workbench = WorkbenchExecutionService(session, user_id=owner.id)
        plan = await workbench.build_plan(project=project, execution_input=command)
        assert plan.credential_revision_id is None and plan.connection_revision_id is not None
        proof = await workbench.preview_compiler_contract(project=project, plan=plan)
        run = await workbench.create_and_dispatch(
            project=project,
            execution_input=command,
            prepared_plan=plan,
            confirmed_compiler_wire_fingerprint=proof.wire_fingerprint,
        )
        await session.commit()
        result = await execute_media_node_run(session, node_run_id=run.id, store=store)
        operation = (
            await session.scalars(
                select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
            )
        ).one()
        assert (
            operation.status == "succeeded"
            and operation.provider_operation_id is None
            and operation.resume_token is None
        )
        assert (
            operation.credential_revision_id is None
            and operation.response_summary["poll_count"] == 0
        )
        artifact = await session.get(Artifact, result.artifact_id)
        assert artifact.mime_type == "image/png" and artifact.width == artifact.height == 1024
        assert await store.get_bytes(object_key=artifact.object_key) == png(
            "red" if label == "alpha" else "blue"
        )
        await execute_media_node_run(session, node_run_id=run.id, store=store)
        revision_id, generation_ids = await service.generation_verified_bindings(
            workspace_id=project.workspace_id, connection_id=connection.id
        )
        assert revision_id == plan.connection_revision_id and generation_ids == {binding.id}
        # A lost synchronous response remains unrecoverable, but a deliberate
        # no-auth identity must never be reported as a missing encrypted key.
        from app.execution.provider_recovery_audit import inspect_provider_operation

        operation.status = "unknown_submission"
        await session.flush()
        audit = await inspect_provider_operation(
            session, operation=operation, run=run, workspace_id=project.workspace_id
        )
        assert "EXECUTION_IDENTITY_CREDENTIAL_UNAVAILABLE" not in audit.blockers
        assert "PROVIDER_SUBMISSION_UNKNOWN" in audit.blockers
        assert "RESUME_TOKEN_UNAVAILABLE" in audit.blockers
        assert audit.as_dict()["provider_calls"] == 0
        assert not session.new and not session.dirty and not session.deleted
        _, generation_ids = await service.generation_verified_bindings(
            workspace_id=project.workspace_id, connection_id=connection.id
        )
        assert not generation_ids
        # A successful old operation is retained, but cannot certify a newly
        # edited endpoint under the same mutable connection ID.
        operation.status = "succeeded"
        await service.update_connection(
            workspace_id=project.workspace_id,
            connection_id=connection.id,
            actor=owner,
            display_name=None,
            enabled=None,
            base_url=f"https://new-{label}.test/v1",
        )
        changed_revision, generation_ids = await service.generation_verified_bindings(
            workspace_id=project.workspace_id, connection_id=connection.id
        )
        assert changed_revision != revision_id and not generation_ids
        artifacts.append(artifact)
        bindings.append(binding)
    assert len(sent) == 2 and {json.loads(r.content)["model"] for r in sent} == {
        "model-alpha",
        "model-beta",
    }
    assert (
        artifacts[0].id != artifacts[1].id
        and artifacts[0].content_hash != artifacts[1].content_hash
    )
    assert (
        bindings[0].id != bindings[1].id
        and bindings[0].catalog_entry_id == bindings[1].catalog_entry_id
    )
    assert (
        contract.contract_manifest_hash
        == original_hash
        == hash_manifest(contract.capability_manifest_json)
    )


async def test_frozen_bearer_connection_overrides_process_no_auth(session, monkeypatch):
    from app.config import clear_settings_cache, get_settings
    from app.providers.connection_service import ProviderConnectionService
    from app.providers.workspace_credentials import runtime_connection_settings
    from cryptography.fernet import Fernet
    from tests.unit.test_workbench_execution import _seed

    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    monkeypatch.setenv("OPENAI_COMPATIBLE_MEDIA_AUTH_MODE", "none")
    clear_settings_cache()
    try:
        project, _, owner = await _seed(session)
        service = ProviderConnectionService(session)
        connection = await service.create_connection(
            workspace_id=project.workspace_id,
            actor=owner,
            provider_type="openai_compatible_media",
            protocol_profile=OPENAI_IMAGES_PROFILE,
            display_name="Bearer fixture",
            base_url="https://bearer.test/v1",
            auth_mode="bearer",
            api_key="frozen-fixture-key",
            enabled=True,
        )
        assert get_settings().openai_compatible_media_auth_mode == "none"
        runtime_settings = await runtime_connection_settings(session, connection=connection)
        probe_settings = await service._connection_settings(connection)
        for resolved in (runtime_settings, probe_settings):
            assert resolved.openai_compatible_media_auth_mode == "bearer"
            assert resolved.openai_compatible_media_api_key == "frozen-fixture-key"
    finally:
        clear_settings_cache()


async def test_historical_binding_list_does_not_invent_a_missing_revision(session):
    from app.providers.connection_service import ProviderConnectionService
    from app.providers.models import ProviderConnectionRevision
    from sqlalchemy import select
    from tests.unit.test_workbench_execution import _seed

    project, binding, _ = await _seed(session)
    # Only this isolated fixture is deliberately missing a historical fact.
    revision = (await session.scalars(select(ProviderConnectionRevision))).one()
    await session.delete(revision)
    await session.flush()
    service = ProviderConnectionService(session)
    revision_id, verified = await service.generation_verified_bindings(
        workspace_id=project.workspace_id, connection_id=binding.connection_id
    )
    assert revision_id is None and not verified
    rows = await service.list_model_bindings(
        workspace_id=project.workspace_id, connection_id=binding.connection_id
    )
    assert [row.id for row in rows] == [binding.id]
    assert not list(await session.scalars(select(ProviderConnectionRevision)))
    assert not session.new and not session.dirty and not session.deleted
