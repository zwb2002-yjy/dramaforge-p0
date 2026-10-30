"""Proxy ownership, single configuration authority and uncertain-write recovery."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from app.access.models import User, Workspace
from app.config import Settings
from app.providers.connection_service import ProviderConnectionService
from app.providers.litellm_gateway.management import (
    GatewayKeyWrite,
    GatewayManagementClient,
    GatewayModelWrite,
    GatewayReference,
)
from app.providers.litellm_gateway.management_service import GatewayModelService
from app.providers.litellm_gateway.model_catalog import LiteLLMModelCatalogSyncService
from app.providers.models import ProviderConnectionRevision
from app.providers.registry import ModelRegistry
from app.providers.workspace_credentials import configured_byok_keyring
from app.security.models import EncryptedProviderCredential
from app.shared.base import Base
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from app.shared.security import CSRF_HEADER
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as scoped:
        yield scoped
    await engine.dispose()


class ProxyFixture:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.creates = 0
        self.updates = 0
        self.timeout_without_write = False

    async def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer restricted-model-admin"
        if request.method == "GET":
            identifier = request.url.params["litellm_model_id"]
            row = self.rows.get(identifier)
            if row is None:
                return httpx.Response(
                    400,
                    json={
                        "detail": {"error": f"Model id = {identifier} not found on litellm proxy"}
                    },
                )
            return httpx.Response(200, json={"data": [row]})
        body = json.loads(request.content)
        if request.url.path == "/model/new":
            self.creates += 1
            if self.timeout_without_write:
                raise httpx.ReadTimeout("synthetic response loss", request=request)
            self.rows[body["model_info"]["id"]] = body
        elif request.method == "PATCH" and request.url.path.endswith("/update"):
            self.updates += 1
            row = self.rows[body["model_info"]["id"]]
            row["model_info"].update(body["model_info"])
            row["litellm_params"].update(body["litellm_params"])
        else:
            raise AssertionError("unexpected management endpoint")
        return httpx.Response(200, json={"ok": True})


async def fixture(
    session: AsyncSession,
) -> tuple[User, Workspace, Settings, ProxyFixture, GatewayModelService]:
    user = User(
        email=f"gateway-{uuid4().hex}@example.test", display_name="Owner", password_hash="fixture"
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Gateway fixture")
    session.add(workspace)
    await session.flush()
    settings = Settings(
        _env_file=None,
        litellm_gateway_url="http://proxy.internal:4000",
        litellm_api_key="restricted-data-key",
        litellm_model_admin_key="restricted-model-admin",
        byok_fernet_key=Fernet.generate_key().decode(),
        byok_keyring="",
        session_secret="fixture-management-fingerprint-secret",
    )
    proxy = ProxyFixture()
    client = GatewayManagementClient(settings, transport=httpx.MockTransport(proxy.handle))
    return (
        user,
        workspace,
        settings,
        proxy,
        GatewayModelService(session, settings=settings, client=client),
    )


def model() -> GatewayModelWrite:
    return GatewayModelWrite(
        request_id=uuid4(),
        display_name="Local text model",
        base_url="https://upstream.example/v1",
        model_id="physical-chat",
        api_key="upstream-secret-only-for-proxy",
    )


async def test_upstream_secret_and_url_never_become_drama_configuration(
    session: AsyncSession,
) -> None:
    user, workspace, settings, proxy, manager = await fixture(session)
    body = model()
    connection = await manager.register(workspace_id=workspace.id, actor=user, body=body)
    reference = GatewayReference.model_validate(connection.gateway_ref)
    assert reference.state == "ready" and proxy.creates == 1
    assert connection.base_url == settings.litellm_gateway_url
    assert body.base_url not in json.dumps(connection.gateway_ref)
    assert body.api_key.get_secret_value() not in json.dumps(connection.gateway_ref)
    credential = await session.get(EncryptedProviderCredential, connection.credential_id)
    assert credential is not None
    assert (
        configured_byok_keyring(settings).decrypt(
            ciphertext=credential.ciphertext, key_version=credential.key_version
        )
        == settings.litellm_api_key
    )
    read = await manager.configuration(
        workspace_id=workspace.id, actor=user, connection_id=connection.id
    )
    assert read.base_url == body.base_url
    assert "api_key" not in read.model_dump()
    again = await manager.register(workspace_id=workspace.id, actor=user, body=body)
    assert again.id == connection.id and proxy.creates == 1


async def test_same_request_id_cannot_mutate_an_existing_target(session: AsyncSession) -> None:
    user, workspace, _, proxy, manager = await fixture(session)
    body = model()
    await manager.register(workspace_id=workspace.id, actor=user, body=body)
    with pytest.raises(ConflictError):
        await manager.register(
            workspace_id=workspace.id,
            actor=user,
            body=body.model_copy(update={"model_id": "different-weight"}),
        )
    assert proxy.creates == 1


async def test_response_loss_never_reposts_an_unconfirmed_create(session: AsyncSession) -> None:
    user, workspace, _, proxy, manager = await fixture(session)
    proxy.timeout_without_write = True
    body = model()
    first = await manager.register(workspace_id=workspace.id, actor=user, body=body)
    assert GatewayReference.model_validate(first.gateway_ref).state == "unknown"
    again = await manager.register(workspace_id=workspace.id, actor=user, body=body)
    assert again.id == first.id and proxy.creates == 1
    assert GatewayReference.model_validate(again.gateway_ref).state == "unknown"


async def test_proxy_created_local_commit_failed_can_reconcile_without_second_create(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, workspace, settings, proxy, manager = await fixture(session)
    body = model()
    original = manager._commit
    commits = 0

    async def fail_final(actor: User, workspace_id):
        nonlocal commits
        commits += 1
        if commits == 3:
            raise RuntimeError("synthetic local write failure after remote create")
        await original(actor, workspace_id)

    monkeypatch.setattr(manager, "_commit", fail_final)
    with pytest.raises(RuntimeError, match="synthetic local"):
        await manager.register(workspace_id=workspace.id, actor=user, body=body)
    await session.rollback()
    # A fresh API request reloads its authenticated context after rollback.
    await session.refresh(user)
    await session.refresh(workspace)
    recovered = GatewayModelService(session, settings=settings, client=manager.client)
    connection = await recovered.register(workspace_id=workspace.id, actor=user, body=body)
    assert GatewayReference.model_validate(connection.gateway_ref).state == "ready"
    assert proxy.creates == 1


async def test_new_target_creates_version_without_rewriting_old_revision(
    session: AsyncSession,
) -> None:
    user, workspace, _, proxy, manager = await fixture(session)
    first = await manager.register(workspace_id=workspace.id, actor=user, body=model())
    before = GatewayReference.model_validate(first.gateway_ref)
    second = model().model_copy(update={"base_url": "https://another.example/v1"})
    updated = await manager.register(
        workspace_id=workspace.id, actor=user, body=second, connection_id=first.id
    )
    after = GatewayReference.model_validate(updated.gateway_ref)
    assert before.deployment_id != after.deployment_id and proxy.creates == 2
    revisions = (
        await session.scalars(
            select(ProviderConnectionRevision).where(
                ProviderConnectionRevision.connection_id == first.id
            )
        )
    ).all()
    assert any(row.gateway_ref == before.model_dump(mode="json") for row in revisions)
    assert str(before.deployment_id) in proxy.rows


async def test_key_rotation_keeps_logical_model_and_tracks_new_revision(
    session: AsyncSession,
) -> None:
    user, workspace, _, proxy, manager = await fixture(session)
    connection = await manager.register(workspace_id=workspace.id, actor=user, body=model())
    before = GatewayReference.model_validate(connection.gateway_ref)
    body = GatewayKeyWrite(request_id=uuid4(), api_key="new-upstream-secret")
    rotated = await manager.rotate_key(
        workspace_id=workspace.id, actor=user, connection_id=connection.id, body=body
    )
    after = GatewayReference.model_validate(rotated.gateway_ref)
    assert after.state == "ready" and after.key_revision == 2
    assert after.deployment_id == before.deployment_id and after.alias == before.alias
    assert proxy.creates == proxy.updates == 1
    await manager.rotate_key(
        workspace_id=workspace.id, actor=user, connection_id=connection.id, body=body
    )
    assert proxy.updates == 1


async def test_drift_and_cross_workspace_cannot_silently_adopt_a_remote_config(
    session: AsyncSession,
) -> None:
    user, workspace, _, proxy, manager = await fixture(session)
    connection = await manager.register(workspace_id=workspace.id, actor=user, body=model())
    other = User(
        email=f"other-{uuid4().hex}@example.test", display_name="Other", password_hash="fixture"
    )
    session.add(other)
    await session.flush()
    with pytest.raises(NotFoundError):
        await manager.configuration(
            workspace_id=workspace.id, actor=other, connection_id=connection.id
        )
    reference = GatewayReference.model_validate(connection.gateway_ref)
    proxy.rows[str(reference.deployment_id)]["litellm_params"]["model"] = "openai/changed-weight"
    result = await manager.reconcile(
        workspace_id=workspace.id, actor=user, connection_id=connection.id
    )
    assert GatewayReference.model_validate(result.gateway_ref).state == "unknown"
    assert proxy.creates == 1


async def test_managed_connections_cannot_use_legacy_credential_or_discovery_writers(
    session: AsyncSession,
) -> None:
    user, workspace, _, _, manager = await fixture(session)
    connection = await manager.register(workspace_id=workspace.id, actor=user, body=model())
    service = ProviderConnectionService(session)
    with pytest.raises(ValidationAppError, match="Proxy"):
        await service.update_credential(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=user,
            api_key="must-not-be-stored",
        )
    with pytest.raises(ValidationAppError, match="Proxy"):
        await service.update_connection(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=user,
            base_url="https://wrong.example",
            display_name=None,
            enabled=None,
        )
    with pytest.raises(ValidationAppError, match="Proxy"):
        await service.probe(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=user,
            capability="auth_models",
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"litellm_gateway_url": "http://another-proxy.internal:4000"},
        {"litellm_api_key": "another-data-plane-key"},
    ],
)
async def test_global_proxy_or_data_key_change_cannot_rebind_existing_connection(
    session: AsyncSession, changed: dict[str, str]
) -> None:
    user, workspace, _, proxy, manager = await fixture(session)
    connection = await manager.register(workspace_id=workspace.id, actor=user, body=model())
    before = dict(connection.gateway_ref or {})
    manager.settings = manager.settings.model_copy(update=changed)
    with pytest.raises(ConflictError, match="data-plane"):
        await manager.register(
            workspace_id=workspace.id, actor=user, body=model(), connection_id=connection.id
        )
    assert connection.gateway_ref == before and proxy.creates == 1
    with pytest.raises(ConflictError, match="data-plane"):
        await manager.reconcile(workspace_id=workspace.id, actor=user, connection_id=connection.id)


def test_api_routes_require_owner_context_and_keep_upstream_key_write_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        litellm_gateway_url="http://proxy.internal:4000",
        litellm_api_key="restricted-data-key",
        litellm_model_admin_key="restricted-model-admin",
        byok_fernet_key=Fernet.generate_key().decode(),
        byok_keyring="",
        session_secret="fixture-management-fingerprint-secret",
    )
    proxy = ProxyFixture()
    management_client = GatewayManagementClient(
        settings, transport=httpx.MockTransport(proxy.handle)
    )
    monkeypatch.setattr(
        "app.providers.litellm_gateway.management_service.get_settings", lambda: settings
    )
    monkeypatch.setattr(GatewayModelService, "client", property(lambda self: management_client))
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"management-api-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Model Owner",
        },
    )
    assert registration.status_code == 201, registration.text
    workspace_id = client.get("/api/v1/workspaces").json()[0]["id"]
    client.headers["X-Workspace-Id"] = workspace_id
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    body = model().model_dump(mode="json")
    body["api_key"] = "upstream-secret-only-for-proxy"
    path = f"/api/v1/workspaces/{workspace_id}/provider-connections/gateway"
    blocked = client.post(path, json=body)
    assert blocked.status_code == 403 and proxy.creates == 0
    legacy = client.post(
        f"/api/v1/workspaces/{workspace_id}/provider-connections",
        json={
            "provider_type": "litellm",
            "protocol_profile": "openai_chat_v1",
            "display_name": "Legacy attempt",
            "base_url": body["base_url"],
            "api_key": body["api_key"],
        },
        headers={CSRF_HEADER: csrf},
    )
    assert legacy.status_code == 422
    assert legacy.json()["details"]["code"] == "LLM_PROXY_MANAGEMENT_REQUIRED"
    created = client.post(path, json=body, headers={CSRF_HEADER: csrf})
    assert created.status_code == 201, created.text
    saved = created.json()
    assert saved["gateway_ref"]["state"] == "ready"
    assert saved["base_url"] == settings.litellm_gateway_url
    assert body["api_key"] not in created.text
    replay = client.post(path, json=body, headers={CSRF_HEADER: csrf})
    assert replay.json()["id"] == saved["id"] and proxy.creates == 1
    config = client.get(
        f"/api/v1/workspaces/{workspace_id}/provider-connections/{saved['id']}/gateway/configuration"
    )
    assert config.status_code == 200 and config.json()["base_url"] == body["base_url"]
    assert body["api_key"] not in config.text
    canary = "sensitive-validation-canary-" * 200
    invalid = client.post(path, json={**body, "api_key": canary}, headers={CSRF_HEADER: csrf})
    assert invalid.status_code == 422
    assert "sensitive-validation-canary" not in invalid.text
    assert all("input" not in error for error in invalid.json()["details"]["errors"])
    assert proxy.creates == 1
    wrong_scope = client.post(
        f"/api/v1/workspaces/{uuid4()}/provider-connections/gateway",
        json=body,
        headers={CSRF_HEADER: csrf},
    )
    assert wrong_scope.status_code == 404 and proxy.creates == 1


async def test_managed_aliases_are_not_exposed_through_global_discovery() -> None:
    class Discovery:
        async def list_models(self):
            return ["legacy-configured", "df-" + "a" * 32]

    registry = ModelRegistry()
    synced = await LiteLLMModelCatalogSyncService(client=Discovery(), registry=registry).sync()
    assert synced == ["litellm/legacy-configured"]
    assert registry.get_or_none("litellm/" + "df-" + "a" * 32) is None


@pytest.mark.parametrize("operation", ["create", "rotate_key"])
async def test_superseded_request_cannot_restore_old_target_or_key(
    session: AsyncSession, operation: str
) -> None:
    user, workspace, _, proxy, manager = await fixture(session)
    first = model()
    connection = await manager.register(workspace_id=workspace.id, actor=user, body=first)
    if operation == "create":
        await manager.register(
            workspace_id=workspace.id, actor=user, body=model(), connection_id=connection.id
        )

        async def replay():
            return await manager.register(
                workspace_id=workspace.id, actor=user, body=first, connection_id=connection.id
            )
    else:
        key_a = GatewayKeyWrite(request_id=uuid4(), api_key="key-a")
        await manager.rotate_key(
            workspace_id=workspace.id, actor=user, connection_id=connection.id, body=key_a
        )
        await manager.rotate_key(
            workspace_id=workspace.id,
            actor=user,
            connection_id=connection.id,
            body=GatewayKeyWrite(request_id=uuid4(), api_key="key-b"),
        )

        async def replay():
            return await manager.rotate_key(
                workspace_id=workspace.id, actor=user, connection_id=connection.id, body=key_a
            )

    before = dict(connection.gateway_ref)
    creates, updates = proxy.creates, proxy.updates
    with pytest.raises(ConflictError) as error:
        await replay()
    assert error.value.details["code"] == "GATEWAY_REQUEST_SUPERSEDED"
    assert connection.gateway_ref == before
    assert (proxy.creates, proxy.updates) == (creates, updates)
