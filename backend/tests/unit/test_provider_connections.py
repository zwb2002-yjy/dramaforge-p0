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
from app.shared.errors import NotFoundError
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


def test_connection_api_is_fixed_write_only_and_duplicate_is_conflict(
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
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CONFLICT"


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
async def test_credential_rotation_clears_capability_and_quality_flags(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest

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
    manifest = next(
        m for m in SEED_MANIFESTS if m["model_id"] == "agnes-image-2.1-flash"
    )
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
        budget_authorized=0,
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

    rotated = await service.update_credential(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        api_key="second-secret",
    )
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
    ) is None

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
async def test_owner_can_freeze_account_pricing_on_exact_binding(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date
    from decimal import Decimal

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest

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
    manifest = next(
        item for item in SEED_MANIFESTS if item["model_id"] == "agnes-image-2.1-flash"
    )
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
    binding = await service.create_model_binding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        media_type="image",
        model_id="agnes-image-2.1-flash",
        purpose="keyframe",
        enabled=True,
    )

    frozen = await service.set_binding_pricing(
        workspace_id=workspace.id,
        connection_id=connection.id,
        model_binding_id=binding.id,
        actor=user,
        unit_amount=Decimal("0.125"),
        currency="usd",
        billing_unit="per_generated_image",
        source_note="account console price",
    )

    assert frozen.pricing_snapshot_json["unit_amount"] == "0.125"
    assert frozen.pricing_snapshot_json["currency"] == "USD"
    assert frozen.pricing_snapshot_json["verified_by"] == str(user.id)
