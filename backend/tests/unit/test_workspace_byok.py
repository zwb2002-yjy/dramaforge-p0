"""Workspace BYOK API and resolver tests without real provider traffic."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.config import Settings, clear_settings_cache
from app.providers.workspace_credentials import (
    WorkspaceCredentialConfigurationError,
    settings_for_workspace_provider,
)
from app.security.byok_keyring import parse_keyring
from app.security.credentials import store_credential
from app.security.models import EncryptedProviderCredential
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _register_and_get_workspace(client: TestClient) -> tuple[str, str]:
    email = f"byok-{uuid4().hex}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "display_name": "BYOK Owner"},
    )
    assert response.status_code == 201
    workspaces = client.get("/api/v1/workspaces")
    assert workspaces.status_code == 200
    workspace_id = str(workspaces.json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id, email


def test_workspace_byok_api_stores_without_readback(client: TestClient, monkeypatch) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    workspace_id, _ = _register_and_get_workspace(client)

    response = client.put(
        f"/api/v1/workspaces/{workspace_id}/provider-credentials",
        json={"provider": "text", "api_key": "workspace-text-secret"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 200
    assert response.json() == {"provider": "text", "configured": True, "key_version": "v1"}
    assert "workspace-text-secret" not in response.text
    status = client.get(f"/api/v1/workspaces/{workspace_id}/provider-credentials/text")
    assert status.status_code == 200
    assert status.json() == {"provider": "text", "configured": True, "key_version": None}


def test_workspace_byok_requires_workspace_owner(client: TestClient, monkeypatch) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    workspace_id, _ = _register_and_get_workspace(client)
    assert client.post(
        "/api/v1/auth/register",
        json={
            "email": f"intruder-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    ).status_code == 201
    denied = client.put(
        f"/api/v1/workspaces/{workspace_id}/provider-credentials",
        json={"provider": "text", "api_key": "intruder-secret"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert denied.status_code == 403


def test_workspace_byok_rejects_a_different_same_owner_workspace_context(
    client: TestClient, monkeypatch
) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    workspace_a, _ = _register_and_get_workspace(client)
    workspace_b = client.post(
        "/api/v1/workspaces",
        json={"name": "Other workspace"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert workspace_b.status_code == 201

    denied = client.put(
        f"/api/v1/workspaces/{workspace_b.json()['id']}/provider-credentials",
        json={"provider": "text", "api_key": "wrong-context-secret"},
        headers={"X-CSRF-Token": _csrf(client), "X-Workspace-Id": workspace_a},
    )
    assert denied.status_code == 404


def test_workspace_credential_resolver_overrides_environment_and_keeps_ciphertext() -> None:
    async def run() -> None:
        load_all_models()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        old_key = Fernet.generate_key().decode("ascii")
        workspace_key = Fernet.generate_key().decode("ascii")
        keyring = parse_keyring(
            primary_version="v2", encoded=f"v1:{old_key},v2:{workspace_key}", legacy_key="",
        )
        owner_id, workspace_id = uuid4(), uuid4()
        config = Settings(
            app_env="development",
            byok_primary_key_version="v2",
            byok_keyring=f"v1:{old_key},v2:{workspace_key}",
            text_llm_enabled=True,
            text_llm_api_key="environment-key",
            text_llm_base_url="https://text.example/v1",
        )
        async with factory() as session:
            session.add(User(
                id=owner_id, email="owner@example.com",
                display_name="Owner", password_hash="hash",
            ))
            session.add(Workspace(
                id=workspace_id, owner_user_id=owner_id,
                name="Resolver workspace",
            ))
            await session.flush()
            record = await store_credential(
                session, workspace_id=workspace_id, provider="text",
                plaintext="workspace-key", keyring=keyring,
            )
            await session.commit()
            resolved = await settings_for_workspace_provider(
                session, workspace_id=workspace_id,
                provider="text", settings=config,
            )
            assert resolved.text_llm_api_key == "workspace-key"
            assert config.text_llm_api_key == "environment-key"
            stored = await session.get(EncryptedProviderCredential, record.id)
            assert stored is not None
            assert "workspace-key" not in stored.ciphertext

            unavailable = Settings(
                app_env="development", byok_primary_key_version="v2", byok_keyring=f"v1:{old_key}",
                text_llm_enabled=True, text_llm_api_key="environment-key", text_llm_base_url="https://text.example/v1",
            )
            with pytest.raises(WorkspaceCredentialConfigurationError) as error:
                await settings_for_workspace_provider(
                    session, workspace_id=workspace_id,
                    provider="text", settings=unavailable,
                )
            assert error.value.code == "WORKSPACE_BYOK_UNAVAILABLE"
        async with factory() as session:
            assert (
                await settings_for_workspace_provider(
                    session, workspace_id=uuid4(),
                    provider="text", settings=config,
                )
                is config
            )
        await engine.dispose()

    asyncio.run(run())
