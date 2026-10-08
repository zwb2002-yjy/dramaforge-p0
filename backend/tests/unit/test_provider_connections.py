"""Workspace-scoped Agnes Connection and evidence lifecycle tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.config import clear_settings_cache
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import ProviderCapabilityEvidence, ProviderModelBinding
from app.shared.base import Base
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.security import CSRF_HEADER, hash_password
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _register_and_select_workspace(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"connection-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Connection Owner",
        },
    )
    assert response.status_code == 201, response.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def test_same_protocol_connections_are_independent_and_credentials_are_write_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyring_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{keyring_key}")
    clear_settings_cache()
    workspace_id = _register_and_select_workspace(client)
    secret = "agnes-api-secret-never-returned"

    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/provider-connections",
        json={
            "provider_type": "agnes",
            "display_name": "Ignored display is accepted",
            "protocol_profile": "agnes_cn_v1",
            "api_key": secret,
            "enabled": True,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["base_url"] == "https://api.agnes-ai.cn"
    assert body["protocol_profile"] == "agnes_cn_v1"
    assert body["credential_configured"] is True
    # The read model reports the stored credential instead of assuming one: the
    # two fields must never contradict each other.
    assert body["credential_key_version"] is not None
    assert body["credential_configured"] is (body["credential_key_version"] is not None)
    assert "api_key" not in body
    assert secret not in created.text

    listed = client.get(f"/api/v1/workspaces/{workspace_id}/provider-connections")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert secret not in listed.text

    duplicate = client.post(
        f"/api/v1/workspaces/{workspace_id}/provider-connections",
        json={
            "provider_type": "agnes",
            "display_name": "Duplicate",
            "protocol_profile": "agnes_cn_v1",
            "api_key": "second-secret",
            "enabled": True,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] != body["id"]
    assert "credential_id" not in duplicate.json()
    listed = client.get(f"/api/v1/workspaces/{workspace_id}/provider-connections")
    assert len(listed.json()) == 2
    assert "second-secret" not in listed.text


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed_owner(session: AsyncSession) -> tuple[User, Workspace]:
    user = User(
        email=f"connection-service-{uuid4().hex}@example.com",
        display_name="Connection Service",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Connection-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return user, workspace


@pytest.mark.asyncio
@pytest.mark.parametrize("base_url", ["https://text.example.test", "https://text.example.test/v1"])
async def test_text_catalog_uses_the_same_normalized_url_and_own_key_as_litellm(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    import httpx

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="文本服务",
        api_key="text-only-key",
        enabled=True,
        provider_type="litellm",
        protocol_profile="openai_chat_v1",
        base_url=base_url,
    )
    requests: list[tuple[str, str]] = []

    async def get(
        _client: httpx.AsyncClient, url: str, *, headers: dict[str, str]
    ) -> httpx.Response:
        requests.append((url, headers["Authorization"]))
        return httpx.Response(200, json={"data": [{"id": "my-chat"}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    evidence = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        capability="auth_models",
    )
    assert requests == [("https://text.example.test/v1/models", "Bearer text-only-key")]
    assert evidence.status == "passed"
    assert evidence.discovered_model_ids == ["my-chat"]
    from app.api.v1.provider_connections import _connection_read, _probe_read

    original = await _connection_read(service, connection)
    historical = _probe_read(evidence)
    assert original.connection_revision_id == historical.connection_revision_id
    renamed = await service.update_connection(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        display_name="改名",
        enabled=None,
    )
    assert (
        await _connection_read(service, renamed)
    ).connection_revision_id == original.connection_revision_id
    changed = await service.update_connection(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        base_url="https://other-text.example.test/v1",
        display_name=None,
        enabled=None,
    )
    changed_read = await _connection_read(service, changed)
    assert changed_read.connection_revision_id != historical.connection_revision_id
    assert changed_read.verification_status == "unverified"
    rotated = await service.update_credential(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        api_key="rotated-fixture",
    )
    assert (
        await _connection_read(service, rotated)
    ).connection_revision_id != changed_read.connection_revision_id
    assert _probe_read(evidence) == historical
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 403, 429, "empty-catalog"])
async def test_text_registry_uses_current_auth_projection_and_preserves_evidence(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: int | str
) -> None:
    from datetime import timedelta

    import httpx
    from app.providers.litellm_gateway.workspace_registry import workspace_model_registry
    from app.providers.registry import ModelRegistry

    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{Fernet.generate_key().decode('ascii')}")
    clear_settings_cache()
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="Text auth regression",
        api_key="test-only-key",
        enabled=True,
        provider_type="litellm",
        protocol_profile="openai_chat_v1",
        base_url="https://auth.example.test/v1",
    )
    response = httpx.Response(200, json={"data": [{"id": "chat"}]})

    async def get(
        _client: httpx.AsyncClient, url: str, *, headers: dict[str, str]
    ) -> httpx.Response:
        assert url == "https://auth.example.test/v1/models"
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    async def probe() -> ProviderCapabilityEvidence:
        return await service.probe(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=user,
            capability="auth_models",
        )

    async def registered() -> bool:
        registry = await workspace_model_registry(
            session, workspace_id=workspace.id, base_registry=ModelRegistry()
        )
        return registry.get_or_none(f"litellm/{connection.id}/chat") is not None

    passed = await probe()
    assert passed.status == "passed"
    assert await registered()
    passed.tested_at -= timedelta(minutes=1)
    await session.flush()
    response = (
        httpx.Response(200, json={"data": []})
        if failure == "empty-catalog"
        else httpx.Response(int(failure))
    )
    failed = await probe()
    assert failed.status == "failed"
    revoked = failure in {401, 403}
    assert connection.verification_status == ("failed" if revoked else "verified")
    assert await registered() is not revoked
    history = list(await session.scalars(select(ProviderCapabilityEvidence)))
    assert {item.id for item in history} == {passed.id, failed.id}
    failed.tested_at -= timedelta(minutes=1)
    await session.flush()
    response = httpx.Response(200, json={"data": [{"id": "chat"}]})
    assert (await probe()).status == "passed"
    assert await registered()


@pytest.mark.asyncio
async def test_same_named_text_models_keep_connection_and_credentials_separate(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.litellm_gateway.workspace_registry import workspace_model_registry
    from app.providers.registry import ModelRegistry

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    connections = []
    for label in ("a", "b"):
        connection = await service.create_connection(
            workspace_id=workspace.id,
            actor=user,
            display_name=label,
            api_key=f"secret-{label}",
            enabled=True,
            provider_type="litellm",
            protocol_profile="openai_chat_v1",
            base_url=f"https://{label}.example.test/v1",
        )
        revision = await service.current_connection_revision(connection=connection)
        connection.verification_status = "verified"
        session.add(
            ProviderCapabilityEvidence(
                workspace_id=workspace.id,
                connection_id=connection.id,
                capability="auth_models",
                status="passed",
                evidence_level="account_verified",
                request_fingerprint="a" * 64,
                credential_revision=connection.credential_revision,
                created_by=user.id,
                connection_revision_id=revision.id,
                discovered_model_ids=["same-model"],
            )
        )
        connections.append(connection)
    await session.flush()
    registry = await workspace_model_registry(
        session,
        workspace_id=workspace.id,
        base_registry=ModelRegistry(),
    )
    models = [registry.get(f"litellm/{connection.id}/same-model") for connection in connections]
    assert models[0].manifest.id != models[1].manifest.id
    assert connections[0].credential_id != connections[1].credential_id
    assert all(model.manifest.model_name == "same-model" for model in models)
    assert {model.manifest.metadata["connection_id"] for model in models} == {
        str(connection.id) for connection in connections
    }
    # The same alias on two connections stays distinguishable in pickers.
    assert {model.manifest.display_name.rsplit(" · ", 1)[-1] for model in models} == {"a", "b"}
    for label, model in zip(("a", "b"), models, strict=True):
        # The adapter receives this text connection's settings, never the
        # selected media provider's address or credential.
        assert model.adapter is not None
        assert model.adapter._settings.litellm_gateway_url == f"https://{label}.example.test/v1"
        assert model.adapter._settings.litellm_api_key == f"secret-{label}"


@pytest.mark.asyncio
async def test_credential_rotation_clears_flags_but_preserves_historical_evidence(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from app.providers.catalog_loader import CATALOG_MODELS, hash_manifest
    from app.providers.catalog_models import ModelCatalogEntry

    keyring_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{keyring_key}")
    clear_settings_cache()
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="Agnes China",
        api_key="first-secret",
        enabled=True,
    )
    manifest = next(m for m in CATALOG_MODELS if m["model_id"] == "agnes-image-2.1-flash")
    session.add(
        ModelCatalogEntry(
            provider_type=manifest["provider_type"],
            protocol_profile=manifest["protocol_profile"],
            model_id=manifest["model_id"],
            model_revision=manifest["model_revision"],
            display_name=manifest["display_name"],
            media_kind=manifest["media_kind"],
            lifecycle="active",
            catalog_source="official_static",
            capability_manifest_json=manifest,
            option_schema_json=manifest.get("option_schema") or {},
            documented_at=date.fromisoformat(manifest["documented_at"]),
            contract_manifest_hash=hash_manifest(manifest),
        )
    )
    await session.flush()
    evidence = ProviderCapabilityEvidence(
        workspace_id=workspace.id,
        connection_id=connection.id,
        capability="image_i2i",
        model_id="agnes-image-2.1-flash",
        status="passed",
        evidence_level="account_verified",
        request_fingerprint="a" * 64,
        currency="USD",
        cost_status="not_reported",
        created_by=user.id,
    )
    session.add(evidence)
    await session.flush()
    binding = await service.create_model_binding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        media_type="image",
        model_id="agnes-image-2.1-flash",
        purpose="keyframe",
        enabled=True,
    )
    binding.account_verified = True
    binding.quality_gated = True
    await session.flush()

    previous_credential_id = connection.credential_id
    previous_credential_revision = connection.credential_revision
    rotated = await service.update_credential(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        api_key="second-secret",
    )
    assert rotated.credential_id != previous_credential_id
    assert rotated.credential_revision == previous_credential_revision + 1
    assert rotated.verification_status == "unverified"
    assert rotated.verified_at is None
    refreshed = await session.get(ProviderModelBinding, binding.id)
    assert refreshed is not None
    assert refreshed.account_verified is False
    assert refreshed.quality_gated is False
    assert (
        await session.scalar(
            select(ProviderCapabilityEvidence.id).where(
                ProviderCapabilityEvidence.connection_id == connection.id
            )
        )
    ) == evidence.id

    other_workspace = Workspace(
        owner_user_id=user.id,
        name=f"Other-{uuid4().hex[:8]}",
    )
    session.add(other_workspace)
    await session.flush()
    with pytest.raises(NotFoundError):
        await service.get_connection(
            workspace_id=other_workspace.id,
            connection_id=connection.id,
        )


@pytest.mark.asyncio
async def test_deprecated_catalog_binding_cannot_be_bound_to_a_new_project(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from app.access.models import Project
    from app.providers.catalog_loader import CATALOG_MODELS, hash_manifest
    from app.providers.catalog_models import ModelCatalogEntry

    keyring_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{keyring_key}")
    clear_settings_cache()
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="Agnes China",
        api_key="secret",
        enabled=True,
    )
    active_manifest = next(
        item for item in CATALOG_MODELS if item["model_id"] == "agnes-image-2.1-flash"
    )
    legacy_manifest = {
        **active_manifest,
        "manifest_version": "2026-08-10",
        "model_revision": "v1",
        "lifecycle": "deprecated",
        "documented_at": "2026-08-10",
    }
    legacy_entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-image-2.1-flash",
        model_revision="v1",
        display_name="Agnes Image Flash",
        media_kind="image",
        lifecycle="deprecated",
        catalog_source="official_static",
        capability_manifest_json=legacy_manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(legacy_manifest),
    )
    session.add(legacy_entry)
    await session.flush()
    legacy_binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="image",
        model_id="agnes-image-2.1-flash",
        purpose="keyframe",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=legacy_entry.id,
        capability_manifest_hash=legacy_entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-image-2.1-flash",
        invoke_model_value="agnes-image-2.1-flash",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(legacy_binding)
    project = Project(
        workspace_id=workspace.id,
        name="New portrait project",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()

    with pytest.raises(ValidationAppError) as caught:
        await service.bind_project(
            project=project,
            purpose="keyframe",
            model_binding_id=legacy_binding.id,
            actor=user,
        )

    assert caught.value.details["code"] == "MODEL_BINDING_CONTRACT_INACTIVE"

    with pytest.raises(ValidationAppError) as probe_caught:
        await service.probe(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=user,
            capability="video_poll_download",
            model_binding_id=legacy_binding.id,
        )

    assert probe_caught.value.details["code"] == "MODEL_BINDING_CONTRACT_INACTIVE"


def test_paid_probe_route_rejects_before_any_provider_dispatch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    from app.providers.registry import ProviderPlugin

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    workspace_id = _register_and_select_workspace(client)
    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/provider-connections",
        json={"api_key": "synthetic-paid-probe-test-key"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201
    connection_id = created.json()["id"]
    factory = Mock(side_effect=AssertionError("Provider must not be constructed"))
    monkeypatch.setattr(ProviderPlugin, "build_client", factory)
    rejected = client.post(
        f"/api/v1/workspaces/{workspace_id}/provider-connections/{connection_id}/probes",
        json={"capability": "image_t2i"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert rejected.status_code == 422
    assert rejected.json()["details"]["code"] == "PAID_PROBE_AUTHORIZATION_UNAVAILABLE"
    factory.assert_not_called()
