"""PostgreSQL persistence proof for the MS1 execution-model snapshot.

The test only runs against an explicitly enabled local PostgreSQL target.  It
writes the secret-free typed resolution through NodeRun.input_snapshot and
reads the JSON value back from PostgreSQL; it never invokes a Provider.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.execution.models import GraphNode, NodeRun
from app.production.models import GraphVersion, ProductionGraph, definition_hash
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolver
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.security.models import EncryptedProviderCredential
from app.shared.db import set_rls_context
from pg_support import available
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def _postgres_is_available() -> bool:
    return available(_database_url())


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _postgres_is_available(),
    reason="set TEST_PG_ENABLED=1 with an explicitly configured PostgreSQL target",
)


@pytest.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _profile_bindings(model_id: str) -> dict[str, object]:
    return {
        ModelSlot.VIDEO_SHOT.value: {
            "slot": ModelSlot.VIDEO_SHOT.value,
            "model_id": f"agnes/{model_id}",
            "native_options": {"seed": 7},
            "enabled": True,
        }
    }


@pytest.mark.asyncio
async def test_execution_model_resolution_round_trips_in_node_run_snapshot_pg(
    pg_session: AsyncSession,
) -> None:
    """A PostgreSQL JSON snapshot retains IDs and never contains credentials."""
    suffix = uuid4().hex[:8]
    user = User(
        email=f"execution-resolution-{suffix}@example.com",
        display_name="Execution resolution",
        password_hash="x",
    )
    pg_session.add(user)
    await pg_session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Execution resolution {suffix}")
    pg_session.add(workspace)
    await pg_session.flush()
    await set_rls_context(pg_session, user_id=user.id, workspace_id=workspace.id)

    project = Project(
        workspace_id=workspace.id,
        name=f"Execution resolution {suffix}",
        aspect_ratio="9:16",
        budget_limit=Decimal("0"),
    )
    pg_session.add(project)
    await pg_session.flush()
    await set_rls_context(
        pg_session,
        user_id=user.id,
        workspace_id=workspace.id,
        project_id=project.id,
    )

    manifest = next(item for item in SEED_MANIFESTS if item["model_id"] == "agnes-video-v2.0")
    model_id = f"execution-resolution-{suffix}"
    entry = ModelCatalogEntry(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id=model_id,
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
    credential = EncryptedProviderCredential(
        workspace_id=workspace.id,
        provider="agnes",
        ciphertext="test-ciphertext",
        key_version="test-key-version",
    )
    pg_session.add(credential)
    await pg_session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type="agnes",
        display_name="Agnes",
        base_url="https://api.agnes-ai.cn",
        protocol_profile="agnes_cn_v1",
        credential_id=credential.id,
        credential_revision=1,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    pg_session.add_all([entry, connection])
    await pg_session.flush()
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
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id=model_id,
        invoke_model_value=model_id,
        created_by=user.id,
        updated_by=user.id,
    )
    profile = ProductionModelProfile(
        workspace_id=workspace.id,
        project_id=None,
        name="Default video",
        version=1,
        is_default=True,
        bindings=_profile_bindings(model_id),
        created_by=user.id,
        updated_by=user.id,
    )
    pg_session.add_all([binding, profile])
    await pg_session.flush()

    resolution = await ExecutionModelResolver(pg_session).resolve(
        project=project,
        slot=ModelSlot.VIDEO_SHOT,
        capability=Capability.VIDEO_IMAGE_TO_VIDEO,
        purpose="video",
        mode_id="explicit_binding",
    )
    assert resolution.status == "RESOLVED"
    snapshot = resolution.model_dump(mode="json")
    assert snapshot["provider_model_binding_id"] == str(binding.id)
    assert snapshot["provider_connection_id"] == str(connection.id)
    assert {"api_key", "base_url", "credential"}.isdisjoint(snapshot)

    graph = ProductionGraph(
        project_id=project.id,
        scope_type="episode",
        scope_entity_id=project.id,
        template_key="execution-model-resolution-pg",
        status="draft",
        created_by=user.id,
    )
    pg_session.add(graph)
    await pg_session.flush()
    version = GraphVersion(
        graph_id=graph.id,
        version_number=1,
        status="draft",
        definition={"nodes": []},
        definition_hash=definition_hash({"nodes": []}),
    )
    pg_session.add(version)
    await pg_session.flush()
    node = GraphNode(
        graph_version_id=version.id,
        node_key="video",
        node_type="video",
        display_name="Video",
    )
    pg_session.add(node)
    await pg_session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"execution-resolution:{suffix}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={"execution_model_resolution": snapshot},
        output_summary={},
        created_by=user.id,
    )
    pg_session.add(run)
    await pg_session.flush()

    stored_snapshot = await pg_session.scalar(
        select(NodeRun.input_snapshot).where(NodeRun.id == run.id)
    )
    assert stored_snapshot is not None
    assert stored_snapshot["execution_model_resolution"] == snapshot

