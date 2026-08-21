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

_FAKE_IMAGE_MANIFEST = {
    "manifest_version": "2026-08-10",
    "provider_type": FAKE_PROVIDER,
    "protocol_profile": FAKE_PROFILE,
    "model_id": "fake-img-model",
    "model_revision": "v1",
    "media_kind": "image",
    "display_name": "Fake Image",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-10",
    "operations": {
        "image.generate": {
            "operation": "image.generate",
            "capabilities": ["image.t2i", "image.i2i"],
            "output_constraints": {},
            "reference_constraints": {},
            "exclusive_groups": [],
        }
    },
    "option_schema": {"namespace": "", "options": {}},
}


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


def test_ark_plugin_is_implemented() -> None:
    from app.providers.volcengine import ArkHubClient

    plugin = get_plugin("volcengine", "ark_cn_v1")
    assert plugin.implemented is True
    assert plugin.default_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert plugin.model_contracts[("image", "keyframe")] == "doubao-seedream-4-0-250828"
    assert plugin.model_contracts[("video", "video")] == "doubao-seedance-2-0-260128"
    # The implemented plugin must build a real Ark protocol client.
    client = plugin.build_client(Settings())
    assert isinstance(client, ArkHubClient)
    profiles = {p.protocol_profile for p in list_plugins()}
    assert {"agnes_cn_v1", "ark_cn_v1", "minimax_cn_v1"} <= profiles


def test_minimax_plugin_is_implemented() -> None:
    from app.providers.minimax import MiniMaxHubClient

    plugin = get_plugin("minimax", "minimax_cn_v1")
    assert plugin.implemented is True
    assert plugin.default_base_url == "https://api.minimaxi.com"
    assert plugin.model_contracts[("image", "keyframe")] == "image-01"
    assert plugin.model_contracts[("video", "video")] == "MiniMax-H3"
    assert plugin.capability_purposes == {"image_i2i": "keyframe", "video_i2v": "video"}
    assert plugin.image_i2i_probe_transport == "public_url"
    assert isinstance(plugin.build_client(Settings()), MiniMaxHubClient)


def test_video_provider_defaults_are_ready_for_account_probes() -> None:
    settings = Settings()
    assert settings.minimax_video_model == "MiniMax-H3"
    assert settings.volcengine_video_model == "doubao-seedance-2-0-260128"


def test_unknown_plugin_is_rejected() -> None:
    from app.providers.connection_service import _resolve_plugin

    with pytest.raises(ValidationAppError):
        _resolve_plugin("nope", "nope_v1")


def test_known_plugins_resolve() -> None:
    from app.providers.connection_service import _resolve_plugin

    assert _resolve_plugin("agnes", "agnes_cn_v1").provider_type == "agnes"
    assert _resolve_plugin("volcengine", "ark_cn_v1").provider_type == "volcengine"
    assert _resolve_plugin("minimax", "minimax_cn_v1").provider_type == "minimax"


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
    from datetime import date

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import hash_manifest

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

    # Seed the fake model's catalog entry (binding now requires one).
    session.add(
        ModelCatalogEntry(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            model_id="fake-img-model",
            model_revision="v1",
            display_name="Fake Image",
            media_kind="image",
            lifecycle="active",
            catalog_source="official_static",
            capability_manifest_json=_FAKE_IMAGE_MANIFEST,
            option_schema_json={},
            documented_at=date.fromisoformat("2026-08-10"),
            contract_manifest_hash=hash_manifest(_FAKE_IMAGE_MANIFEST),
        )
    )
    await session.flush()

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
    assert binding.invoke_model_value == "fake-img-model"
    assert binding.catalog_entry_id is not None
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

    with pytest.raises(ValidationAppError) as pricing_error:
        await service.probe(
            workspace_id=workspace.id,
            connection_id=connection.id,
            actor=user,
            capability="image_t2i",
            model_binding_id=binding.id,
            budget_authorized=Decimal("1"),
        )
    assert pricing_error.value.details["code"] == "PROBE_PRICING_CURRENCY_REQUIRED"
    binding.pricing_snapshot_json = {
        "unit_amount": "0.25",
        "currency": "USD",
        "billing_unit": "per_generated_image",
    }

    evidence = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        capability="image_t2i",
        model_binding_id=binding.id,
        budget_authorized=Decimal("1"),
    )
    assert evidence.status == "passed"
    assert evidence.provider_request_id == "fake-img-1"
    assert evidence.currency == "USD"
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
async def test_auth_models_verifies_only_bindings_listed_by_provider(
    session: AsyncSession,
    fake_registration: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import hash_manifest

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
    bindings: list[ProviderModelBinding] = []
    for model_id in ("fake-img-listed", "fake-img-hidden"):
        manifest = {**_FAKE_IMAGE_MANIFEST, "model_id": model_id}
        session.add(
            ModelCatalogEntry(
                provider_type=FAKE_PROVIDER,
                protocol_profile=FAKE_PROFILE,
                model_id=model_id,
                model_revision="v1",
                display_name=model_id,
                media_kind="image",
                lifecycle="active",
                catalog_source="official_static",
                capability_manifest_json=manifest,
                option_schema_json={},
                documented_at=date.fromisoformat("2026-08-10"),
                contract_manifest_hash=hash_manifest(manifest),
            )
        )
        await session.flush()
        bindings.append(
            await service.create_model_binding(
                workspace_id=workspace.id,
                connection_id=connection.id,
                actor=user,
                media_type="image",
                model_id=model_id,
                purpose="keyframe",
                enabled=True,
            )
        )

    class _ModelsResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"data": [{"id": "fake-img-listed"}]}

    class _ModelsClient:
        async def __aenter__(self) -> _ModelsClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, *args: object, **kwargs: object) -> _ModelsResponse:
            return _ModelsResponse()

    monkeypatch.setattr(
        "app.providers.connection_service.httpx.AsyncClient",
        lambda **kwargs: _ModelsClient(),
    )
    evidence = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        capability="auth_models",
    )

    assert evidence.status == "passed"
    assert connection.verification_status == "verified"
    assert bindings[0].account_verified is True
    assert bindings[1].account_verified is False


@pytest.mark.asyncio
async def test_binding_scoped_probe_only_advances_probed_binding(
    session: AsyncSession,
    fake_registration: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review gate: a binding-scoped probe proves exactly one model. A sibling
    binding on the same connection/purpose must stay unverified."""
    import base64
    import hashlib
    from datetime import date

    from app.access.models import Project
    from app.execution.models import Artifact
    from app.providers.catalog_models import ModelCatalogEntry
    from app.providers.catalog_seed_data import hash_manifest

    _byok_env(monkeypatch)
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
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
    for model_id in ("fake-img-a", "fake-img-b"):
        manifest = dict(_FAKE_IMAGE_MANIFEST)
        manifest["model_id"] = model_id
        session.add(
            ModelCatalogEntry(
                provider_type=FAKE_PROVIDER,
                protocol_profile=FAKE_PROFILE,
                model_id=model_id,
                model_revision="v1",
                display_name=f"Fake {model_id}",
                media_kind="image",
                lifecycle="active",
                catalog_source="official_static",
                capability_manifest_json=manifest,
                option_schema_json={},
                documented_at=date.fromisoformat("2026-08-10"),
                contract_manifest_hash=hash_manifest(manifest),
            )
        )
    await session.flush()
    binding_a = await service.create_model_binding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        media_type="image",
        model_id="fake-img-a",
        purpose="keyframe",
        enabled=True,
    )
    binding_a.pricing_snapshot_json = {
        "unit_amount": "0",
        "currency": "CNY",
        "billing_unit": "per_generated_image",
    }
    binding_b = await service.create_model_binding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        media_type="image",
        model_id="fake-img-b",
        purpose="keyframe",
        enabled=True,
    )
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="9:16", budget_limit=0)
    session.add(project)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"projects/{project.id}/ref.png",
        content_hash=hashlib.sha256(png_bytes).hexdigest(),
        mime_type="image/png",
        byte_size=len(png_bytes),
    )
    session.add(artifact)
    await session.flush()

    class _FakeStore:
        async def get_bytes(self, *, object_key: str) -> bytes:
            return png_bytes

    monkeypatch.setattr("app.providers.connection_service.get_object_store", lambda: _FakeStore())

    evidence = await service.probe(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        capability="image_i2i",
        model_binding_id=binding_a.id,
        reference_artifact_id=artifact.id,
        budget_authorized=Decimal("1"),
    )
    assert evidence.status == "passed"
    assert evidence.model_binding_id == binding_a.id
    assert evidence.capability_manifest_hash == binding_a.capability_manifest_hash
    assert evidence.credential_revision == connection.credential_revision
    assert evidence.currency == "CNY"

    refreshed_a = await session.get(ProviderModelBinding, binding_a.id)
    refreshed_b = await session.get(ProviderModelBinding, binding_b.id)
    assert refreshed_a is not None and refreshed_a.account_verified is True
    assert refreshed_b is not None and refreshed_b.account_verified is False


@pytest.mark.asyncio
async def test_ark_connection_creates_with_plugin_defaults(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok_env(monkeypatch)
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="Ark",
        api_key="ark-secret",
        enabled=True,
        provider_type="volcengine",
        protocol_profile="ark_cn_v1",
    )
    assert connection.provider_type == "volcengine"
    assert connection.protocol_profile == "ark_cn_v1"
    assert connection.base_url == "https://ark.cn-beijing.volces.com/api/v3"


@pytest.mark.asyncio
async def test_minimax_connection_creates_with_plugin_defaults(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok_env(monkeypatch)
    user, workspace = await _seed_owner(session)
    service = ProviderConnectionService(session)
    connection = await service.create_connection(
        workspace_id=workspace.id,
        actor=user,
        display_name="MiniMax",
        api_key="minimax-secret",
        enabled=True,
        provider_type="minimax",
        protocol_profile="minimax_cn_v1",
    )
    assert connection.provider_type == "minimax"
    assert connection.protocol_profile == "minimax_cn_v1"
    assert connection.base_url == "https://api.minimaxi.com"


def test_volcengine_settings_defaults() -> None:
    settings = Settings()
    assert settings.volcengine_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert settings.volcengine_image_model == "doubao-seedream-4-0-250828"
    assert settings.volcengine_configured() is False
    enabled = settings.model_copy(
        update={"volcengine_enabled": True, "volcengine_api_key": "ark-secret"}
    )
    assert enabled.volcengine_configured() is True


def test_minimax_settings_defaults() -> None:
    settings = Settings()
    assert settings.minimax_base_url == "https://api.minimaxi.com"
    assert settings.minimax_image_model == "image-01"
    assert settings.minimax_video_model == "MiniMax-H3"
    assert settings.minimax_configured() is False
    enabled = settings.model_copy(
        update={"minimax_enabled": True, "minimax_api_key": "minimax-secret"}
    )
    assert enabled.minimax_configured() is True


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


@pytest.mark.asyncio
async def test_minimax_workspace_credential_branch(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok_env(monkeypatch)
    user, workspace = await _seed_owner(session)
    await store_credential(
        session,
        workspace_id=workspace.id,
        provider="minimax",
        plaintext="minimax-secret",
        keyring=configured_byok_keyring(),
    )
    cfg = await settings_for_workspace_provider(
        session,
        workspace_id=workspace.id,
        provider="minimax",
    )
    assert cfg.minimax_enabled is True
    assert cfg.minimax_api_key == "minimax-secret"
