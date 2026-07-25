"""Organization BYOK API and resolver tests without real Provider traffic."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.access.models import Organization
from app.config import Settings, clear_settings_cache
from app.providers.organization_credentials import (
    OrganizationCredentialConfigurationError,
    settings_for_organization_provider,
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
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _register_and_create_org(client: TestClient) -> tuple[str, str]:
    email = f"byok-{uuid4().hex}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": "BYOK Owner",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201
    response = client.post(
        "/api/v1/organizations",
        json={"name": "BYOK Org"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201
    return str(response.json()["id"]), email


def test_organization_byok_api_stores_without_readback(client: TestClient, monkeypatch) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    organization_id, _ = _register_and_create_org(client)

    response = client.put(
        f"/api/v1/organizations/{organization_id}/provider-credentials",
        json={"provider": "text", "api_key": "organization-text-secret"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 200
    assert response.json() == {
        "provider": "text",
        "configured": True,
        "key_version": "v1",
    }
    assert "organization-text-secret" not in response.text

    status = client.get(
        f"/api/v1/organizations/{organization_id}/provider-credentials/text"
    )
    assert status.status_code == 200
    assert status.json() == {"provider": "text", "configured": True, "key_version": None}


def test_organization_byok_requires_owner_or_admin(client: TestClient, monkeypatch) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{key}")
    clear_settings_cache()
    organization_id, owner_email = _register_and_create_org(client)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"member-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Member",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201
    member_id = response.json()["id"]
    owner_login = client.post(
        "/api/v1/auth/login",
        json={"email": owner_email, "password": "password123"},
    )
    assert owner_login.status_code == 200
    add_member = client.post(
        f"/api/v1/organizations/{organization_id}/members",
        json={"user_id": member_id, "role": "viewer"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert add_member.status_code == 201
    viewer_login = client.post(
        "/api/v1/auth/login",
        json={"email": response.json()["email"], "password": "password123"},
    )
    assert viewer_login.status_code == 200
    denied = client.put(
        f"/api/v1/organizations/{organization_id}/provider-credentials",
        json={"provider": "text", "api_key": "viewer-secret"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert denied.status_code == 403


def test_organization_credential_resolver_overrides_env_and_keeps_ciphertext() -> None:
    async def run() -> None:
        load_all_models()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        old_key = Fernet.generate_key().decode("ascii")
        organization_key = Fernet.generate_key().decode("ascii")
        keyring = parse_keyring(
            primary_version="v2",
            encoded=f"v1:{old_key},v2:{organization_key}",
            legacy_key="",
        )
        org_id = uuid4()
        config = Settings(
            app_env="development",
            byok_primary_key_version="v2",
            byok_keyring=f"v1:{old_key},v2:{organization_key}",
            text_llm_enabled=True,
            text_llm_api_key="environment-key",
            text_llm_base_url="https://text.example/v1",
        )
        async with factory() as session:
            session.add(Organization(id=org_id, name="Resolver Org"))
            await session.flush()
            record = await store_credential(
                session,
                organization_id=org_id,
                provider="text",
                plaintext="organization-key",
                keyring=keyring,
            )
            await session.commit()
            resolved = await settings_for_organization_provider(
                session,
                organization_id=org_id,
                provider="text",
                settings=config,
            )
            assert resolved.text_llm_api_key == "organization-key"
            assert config.text_llm_api_key == "environment-key"
            stored = await session.get(EncryptedProviderCredential, record.id)
            assert stored is not None
            assert "organization-key" not in stored.ciphertext

            unavailable_config = Settings(
                app_env="development",
                byok_primary_key_version="v2",
                byok_keyring=f"v1:{old_key}",
                text_llm_enabled=True,
                text_llm_api_key="environment-key",
                text_llm_base_url="https://text.example/v1",
            )
            with pytest.raises(OrganizationCredentialConfigurationError) as error:
                await settings_for_organization_provider(
                    session,
                    organization_id=org_id,
                    provider="text",
                    settings=unavailable_config,
                )
            assert error.value.code == "ORGANIZATION_BYOK_UNAVAILABLE"
        async with factory() as session:
            fallback = await settings_for_organization_provider(
                session,
                organization_id=uuid4(),
                provider="text",
                settings=config,
            )
            assert fallback is config
        await engine.dispose()

    asyncio.run(run())
