"""Provider plugin registry and plugin-driven connection service tests.

Proves the extension contract: adding a supplier = registering a plugin, and the
connection service reaches every behavior (create / probe / model binding)
through the registry without a provider-name branch.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.config import Settings, clear_settings_cache
from app.providers import registry as registry_module
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import ProviderCapabilityEvidence, ProviderModelBinding
from app.providers.registry import ProviderPlugin, get_plugin, list_plugins, register_plugin
from app.providers.workspace_credentials import (
    configured_byok_keyring,
    settings_for_workspace_provider,
)
from app.security.credentials import store_credential
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

FAKE_PROVIDER = "fakeprovider"
FAKE_PROFILE = "fakeprofile"


def _byok_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keyring_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{keyring_key}")
    clear_settings_cache()


def test_agnes_plugin_is_implemented() -> None:
    plugin = get_plugin("agnes", "agnes_cn_v1")
    assert plugin.implemented is True
    assert plugin.default_base_url == "https://api.agnes-ai.cn"
    assert plugin.model_contracts[("image", "keyframe")] == "agnes-image-2.1-flash"
    assert plugin.model_contracts[("video", "video")] == "agnes-video-v2.0"
    assert plugin.capability_purposes == {"image_i2i": "keyframe", "video_i2v": "video"}


def test_ark_plugin_is_catalog_only_until_adapter_lands() -> None:
    plugin = get_plugin("volcengine", "ark_cn_v1")
    assert plugin.implemented is False
    assert plugin.default_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    # Catalog-only plugin must refuse to build a client until Phase B lands.
    with pytest.raises(NotImplementedError):
        plugin.build_client(Settings())
    profiles = {p.protocol_profile for p in list_plugins()}
    assert {"agnes_cn_v1", "ark_cn_v1"} <= profiles


def test_unknown_plugin_is_rejected() -> None:
    from app.providers.connection_service import _resolve_plugin

    with pytest.raises(ValidationAppError):
        _resolve_plugin("nope", "nope_v1")


def test_catalog_plugin_is_rejected_until_implemented() -> None:
    from app.providers.connection_service import _resolve_plugin

    with pytest.raises(ValidationAppError):
        _resolve_plugin("volcengine", "ark_cn_v1")


def test_plugin_registration_duplicate_is_rejected() -> None:
    plugin = get_plugin("agnes", "agnes_cn_v1")
    with pytest.raises(ValueError):
        register_plugin(plugin)


class _FakeClient:
    """Protocol-surface stub sufficient for capability probes."""

    def __init__(self, settings: Settings, host: str | None) -> None:
        self.settings = settings
        self.host = host

    async def create_image(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "succeeded",
            "remote_task_id": "fake-img-1",
            "http_status": 200,
        }

    async def create_video(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "queued",
            "remote_task_id": "fake-vid-1",
            "http_status": 202,
        }

    async def poll_video(self, remote_task_id: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "succeeded",
            "http_status": 200,
            "artifact_uri": "https://fake.example.com/v.mp4",
        }


def _fake_plugin() -> ProviderPlugin:
    # settings_prefix/credential_provider_key reuse the existing agnes slots so
    # the fake plugin rides the already-verified Settings/BYOK plumbing; the
    # point is that create/probe/binding need no service branch for its type.
    return ProviderPlugin(
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        display_name="Fake Provider",
        default_base_url="https://fake.example.com",
        implemented=True,
        settings_prefix="agnes",
        credential_provider_key="agnes",
        model_contracts={
            ("image", "keyframe"): "fake-img-model",
            ("video", "video"): "fake-vid-model",
        },
        capability_purposes={"image_i2i": "keyframe", "video_i2v": "video"},
        paid_capabilities=frozenset({"image_t2i", "image_i2i", "video_i2v"}),
        model_list_path="/v1/models",
        client_factory=lambda settings, host: _FakeClient(settings, host),
    )


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest.fixture
def fake_registration() -> Any:
    plugin = _fake_plugin()
    register_plugin(plugin)
    try:
        yield plugin
    finally:
        registry_module._registry.pop((FAKE_PROVIDER, FAKE_PROFILE), None)


async def _seed_owner(session: AsyncSession) -> tuple[User, Workspace]:
    user = User(
        email=f"registry-{uuid4().hex}@example.com",
        display_name="Registry Service",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Registry-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return user, workspace


@pytest.mark.asyncio
async def test_plugin_extension_needs_no_service_branch(
    session: AsyncSession,
    fake_registration: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok_env(monkeypatch)
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)

    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="Fake",
        api_key="secret",
        enabled=True,
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
    )
    assert connection.provider_type == FAKE_PROVIDER
    assert connection.protocol_profile == FAKE_PROFILE
    assert connection.base_url == "https://fake.example.com"

    binding = await service.create_model_binding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        media_type="image",
        model_id="fake-img-model",
        purpose="keyframe",
        enabled=True,
    )
    assert binding.model_id == "fake-img-model"
    with pytest.raises(ValidationAppError):
        await service.create_model_binding(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=user,
            media_type="image",
            model_id="not-a-contract-model",
            purpose="keyframe",
            enabled=True,
        )

    evidence = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        capability="image_t2i",
        budget_authorized=Decimal("1"),
    )
    assert evidence.status == "passed"
    assert evidence.provider_request_id == "fake-img-1"
    assert (
        await session.scalar(
            select(ProviderCapabilityEvidence.id).where(
                ProviderCapabilityEvidence.connection_id == connection.id
            )
        )
        is not None
    )
    refreshed = await session.get(ProviderModelBinding, binding.id)
    assert refreshed is not None
    assert refreshed.account_verified is False  # image_t2i has no purpose mapping


@pytest.mark.asyncio
async def test_ark_catalog_plugin_cannot_create_connection(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok_env(monkeypatch)
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    with pytest.raises(ValidationAppError):
        await service.create_connection(
            workspace_id=workspace.id,
            actor=user,
            display_name="Ark",
            api_key="secret",
            enabled=True,
            provider_type="volcengine",
            protocol_profile="ark_cn_v1",
        )


def test_volcengine_settings_defaults() -> None:
    settings = Settings()
    assert settings.volcengine_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert settings.volcengine_image_model == "doubao-seedream-4-0-250828"
    assert settings.volcengine_configured() is False
    enabled = settings.model_copy(
        update={"volcengine_enabled": True, "volcengine_api_key": "ark-secret"}
    )
    assert enabled.volcengine_configured() is True


@pytest.mark.asyncio
async def test_volcengine_workspace_credential_branch(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok_env(monkeypatch)
    user, workspace = await _seed_owner(session)
    await store_credential(
        session,
        workspace_id=workspace.id,
        provider="volcengine",
        plaintext="ark-secret",
        keyring=configured_byok_keyring(),
    )
    cfg = await settings_for_workspace_provider(
        session,
        workspace_id=workspace.id,
        provider="volcengine",
    )
    assert cfg.volcengine_enabled is True
    assert cfg.volcengine_api_key == "ark-secret"
