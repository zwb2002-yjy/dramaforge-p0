"""MS5-R concrete model-to-runtime resolution tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access import models as _access_models  # noqa: F401
from app.access.models import User, Workspace
from app.providers import catalog_models as _catalog_models  # noqa: F401
from app.providers import models as _provider_models  # noqa: F401
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.providers.registry import ProviderPlugin
from app.providers.runtime import ProviderRuntimeResolver
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed_two_models(
    session: AsyncSession,
) -> tuple[ProviderConnection, ProviderModelBinding, ProviderModelBinding]:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"runtime-resolution-{suffix}@example.com",
        display_name="Runtime resolution",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Runtime {suffix}")
    session.add(workspace)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="same-provider",
        display_name="Same provider",
        base_url="https://provider.example.com",
        protocol_profile="same-profile",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()

    bindings: list[ProviderModelBinding] = []
    for model_id, wire_model, marker in (
        ("model-a", "wire-model-a", "a"),
        ("model-b", "wire-model-b", "b"),
    ):
        manifest_hash = marker * 64
        entry = ModelCatalogEntry(
            provider_type="same-provider",
            protocol_profile="same-profile",
            model_id=model_id,
            model_revision="v1",
            display_name=model_id,
            media_kind="video",
            lifecycle="active",
            catalog_source="official_static",
            capability_manifest_json={"model_id": model_id},
            option_schema_json={},
            documented_at=date(2026, 8, 26),
            contract_manifest_hash=manifest_hash,
        )
        session.add(entry)
        await session.flush()
        binding = ProviderModelBinding(
            workspace_id=workspace.id,
            connection_id=connection.id,
            media_type="video",
            model_id=model_id,
            purpose="video",
            enabled=True,
            documented=True,
            contract_tested=True,
            account_verified=True,
            quality_gated=True,
            catalog_entry_id=entry.id,
            capability_manifest_hash=manifest_hash,
            remote_resource_kind="model",
            remote_resource_id=model_id,
            invoke_model_value=wire_model,
            created_by=user.id,
            updated_by=user.id,
        )
        bindings.append(binding)
        session.add(binding)
        await session.flush()
    return connection, bindings[0], bindings[1]


def _plugin(runtime_calls: list[dict[str, object]]) -> ProviderPlugin:
    def runtime_factory(**kwargs: object) -> object:
        runtime_calls.append(kwargs)
        return object()

    return ProviderPlugin(
        provider_type="same-provider",
        protocol_profile="same-profile",
        display_name="Same provider",
        default_base_url="https://provider.example.com",
        implemented=True,
        settings_prefix="same_provider",
        credential_provider_key="same-provider",
        runtime_factory=runtime_factory,
        compiler_factory=lambda: (object(), object()),
    )


@pytest.mark.asyncio
async def test_binding_runtime_resolution_uses_requested_model_b_not_seed_order(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _connection, binding_a, binding_b = await _seed_two_models(session)
    runtime_calls: list[dict[str, object]] = []
    plugin = _plugin(runtime_calls)
    monkeypatch.setattr(
        "app.providers.registry.get_plugin",
        lambda provider_type, protocol_profile: plugin,
    )

    resolved = await ProviderRuntimeResolver(session).resolve_runtime_for_model_binding(
        model_binding_id=binding_b.id,
    )

    assert resolved.binding is not None
    assert resolved.catalog_entry is not None
    assert resolved.binding.id == binding_b.id
    assert resolved.binding.id != binding_a.id
    assert resolved.catalog_entry.model_id == "model-b"
    assert resolved.model_id == "same-provider/model-b"
    assert resolved.invoke_model_value == "wire-model-b"
    assert resolved.manifest_hash == "b" * 64
    assert len(runtime_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_field",
    ["catalog", "model", "provider", "profile", "hash", "lifecycle", "invoke"],
)
async def test_invalid_binding_catalog_identity_fails_before_runtime_creation(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    invalid_field: str,
) -> None:
    connection, _binding_a, binding_b = await _seed_two_models(session)
    runtime_calls: list[dict[str, object]] = []
    plugin = _plugin(runtime_calls)
    monkeypatch.setattr(
        "app.providers.registry.get_plugin",
        lambda provider_type, protocol_profile: plugin,
    )
    entry = await session.get(ModelCatalogEntry, binding_b.catalog_entry_id)
    assert entry is not None

    if invalid_field == "catalog":
        binding_b.catalog_entry_id = uuid4()
    elif invalid_field == "model":
        entry.model_id = "other-model"
    elif invalid_field == "provider":
        entry.provider_type = "other-provider"
    elif invalid_field == "profile":
        entry.protocol_profile = "other-profile"
    elif invalid_field == "hash":
        binding_b.capability_manifest_hash = "wrong" * 16
    elif invalid_field == "lifecycle":
        entry.lifecycle = "deprecated"
    elif invalid_field == "invoke":
        binding_b.invoke_model_value = None
    await session.flush()

    with pytest.raises(ValidationAppError) as exc_info:
        await ProviderRuntimeResolver(session).resolve_runtime_for_model_binding(
            model_binding_id=binding_b.id,
        )

    assert exc_info.value.details["code"] == "MODEL_RUNTIME_IDENTITY_INVALID"
    assert runtime_calls == []
