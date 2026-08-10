"""Shadow resolve tests: unified path observes legacy resolution, never submits."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.execution.models import ProviderOperation
from app.execution.product_path import _run_shadow_selection
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.models import (
    ProjectProviderBinding,
    ProviderConnection,
    ProviderModelBinding,
)
from app.shared.base import Base
from app.shared.security import hash_password
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


async def _seed(
    session: AsyncSession,
) -> tuple[Project, ProviderModelBinding]:
    user = User(
        email=f"shadow-{uuid4().hex}@example.com",
        display_name="Shadow",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Shadow-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()

    manifest = next(m for m in SEED_MANIFESTS if m["model_id"] == "agnes-video-v2.0")
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
        model_revision="v1",
        display_name="Agnes Video",
        media_kind="video",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(manifest),
    )
    session.add(entry)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=uuid4(),
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()
    binding = ProviderModelBinding(
        workspace_id=workspace.id,
        connection_id=connection.id,
        media_type="video",
        model_id="agnes-video-v2.0",
        purpose="video",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="agnes-video-v2.0",
        invoke_model_value="agnes-video-v2.0",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=project.workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=user.id,
        )
    )
    await session.flush()
    return project, binding


def _op() -> ProviderOperation:
    return ProviderOperation(
        node_run_id=uuid4(),
        attempt_no=1,
        purpose="primary",
        operation_kind="video.generate",
        actual_provider="agnes",
        actual_model="agnes-video-v2.0",
        protocol_profile="agnes_cn_v1",
        request_fingerprint="f" * 64,
        status="created",
        request_summary={"kind": "video"},
        response_summary={},
        submitted_at=None,
    )


@pytest.mark.asyncio
async def test_shadow_resolves_to_same_model_and_records_match(
    session: AsyncSession,
) -> None:
    project, binding = await _seed(session)
    op = _op()
    await _run_shadow_selection(
        session,
        project=project,
        node_type="video",
        prompt="p",
        first_frame=None,
        op=op,
        legacy_provider="agnes",
        legacy_model="agnes-video-v2.0",
    )
    shadow = op.request_summary.get("shadow_selection")
    assert isinstance(shadow, dict)
    assert shadow["resolved"] is True
    assert shadow["provider_type"] == "agnes"
    assert shadow["protocol_profile"] == "agnes_cn_v1"
    assert shadow["invoke_model_value"] == "agnes-video-v2.0"
    assert shadow["model_binding_id"] == str(binding.id)
    assert shadow["matches_legacy"] is True
    assert shadow["legacy_provider"] == "agnes"
    assert shadow["legacy_model"] == "agnes-video-v2.0"


@pytest.mark.asyncio
async def test_shadow_without_project_binding_is_observational_not_fatal(
    session: AsyncSession,
) -> None:
    # Project exists but has no ProjectProviderBinding row.
    user = User(
        email=f"shadow-{uuid4().hex}@example.com",
        display_name="Shadow",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Shadow-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()
    op = _op()
    await _run_shadow_selection(
        session,
        project=project,
        node_type="video",
        prompt="p",
        first_frame=None,
        op=op,
        legacy_provider="agnes",
        legacy_model="agnes-video-v2.0",
    )
    shadow = op.request_summary.get("shadow_selection")
    assert isinstance(shadow, dict)
    assert shadow["resolved"] is False
    assert "error" in shadow
