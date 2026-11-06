"""The account-level existing-task probe uses the actual unified Runtime, GET only."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from app.config import clear_settings_cache
from app.providers.catalog_loader import hash_manifest
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.models import ProviderModelBinding
from cryptography.fernet import Fernet
from tests.unit.model_infra_fixture import unit_video_manifest
from tests.unit.test_provider_probe_safety import _seed
from tests.unit.test_provider_probe_safety import session as session


@pytest.mark.parametrize(
    "provider,profile,path",
    [
        ("agnes", "agnes_cn_v1", "/agnesapi"),
        ("minimax", "minimax_cn_v1", "/v2/query/video_generation/existing-task"),
        ("volcengine", "ark_cn_v1", "/api/v3/contents/generations/tasks/existing-task"),
    ],
)
async def test_actual_runtime_queries_the_same_task_and_frozen_connection_without_create(
    session,
    monkeypatch,
    provider,
    profile,
    path,
):
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", "v1:" + Fernet.generate_key().decode())
    clear_settings_cache()
    actor, workspace, service, connection, _ = await _seed(
        session, provider_type=provider, profile=profile
    )
    manifest = unit_video_manifest()
    manifest.update(
        provider_type=provider, protocol_profile=profile, model_id=f"unit-{provider}-task"
    )
    content_hash = hash_manifest(manifest)
    entry = ModelCatalogEntry(
        provider_type=provider,
        protocol_profile=profile,
        model_id=manifest["model_id"],
        model_revision=manifest["model_revision"],
        display_name="Controlled read-only task",
        media_kind="video",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date(2026, 8, 10),
        contract_manifest_hash=content_hash,
    )
    session.add(entry)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="video",
        model_id=entry.model_id,
        purpose="video",
        enabled=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=content_hash,
        invoke_model_value=entry.model_id,
        account_verified=False,
        quality_gated=False,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(binding)
    await session.flush()
    seen = []

    def response(request):
        seen.append(request)
        assert request.method == "GET" and request.url.path == path
        assert (
            request.headers["Authorization"]
            == "Bearer synthetic-test-key-not-a-provider-credential"
        )
        if provider == "agnes":
            assert request.url.params["video_id"] == "existing-task"
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "video_url": "https://media.invalid/a.mp4",
                "content": {"video_url": "https://media.invalid/a.mp4"},
                "task": {"status": "succeeded", "content": {"url": "https://media.invalid/a.mp4"}},
                "base_resp": {"status_code": 0},
            },
        )

    monkeypatch.setattr(
        "app.providers.egress.guarded_provider_transport",
        lambda **kwargs: httpx.MockTransport(response),
    )
    evidence = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=actor,
        capability="video_poll_download",
        model_binding_id=binding.id,
        remote_task_id="existing-task",
        remote_query_kind="video_id",
    )
    assert len(seen) == 1 and evidence.status == "passed"
    assert evidence.provider_request_id == "existing-task"
    assert (
        evidence.connection_revision_id
        == (await service.current_connection_revision(connection=connection)).id
    )
    assert evidence.credential_revision == connection.credential_revision
    assert evidence.model_binding_id == binding.id
    assert binding.account_verified is False and binding.quality_gated is False
