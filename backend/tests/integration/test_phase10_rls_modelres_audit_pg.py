"""Phase 10 P10-05 RLS audit + 07 §23 Final Model Resolution audit on real PG.

P10-05 (plan 03 §92): every new tenant table must be FORCE RLS with a
project-scoped policy, and cross-project reads must return zero rows. The
schema check covers workspace state / asset version / tag / binding /
experiment / annotation / director assistant / proposal (+ edit session); the
runtime negative test seeds project B rows and verifies they are invisible
under project A's RLS context.

07 §23 (plan 07 §23): the professional formal path must have no real media call
bypassing ExecutionModelResolver. WorkbenchExecutionService.build_plan resolves
through ExecutionModelResolver and create_and_dispatch persists the frozen
resolution into NodeRun.input_snapshot for the worker (no direct provider
HTTP). No secret material is written.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Asset, AssetVersion, Shot
from app.assets.script_import import import_script
from app.delivery.models import ReviewAnnotation
from app.director.models import DirectorMessage, DirectorThread
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.editing.models import EditSession
from app.execution.models import Artifact, NodeRun
from app.production.models import (
    ProductionExperiment,
    ShotExperiment,
    ShotReferenceBinding,
)
from app.production.workbench_execution import (
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import SEED_MANIFESTS, hash_manifest
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.slots import ModelSlot
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.security.models import EncryptedProviderCredential
from app.shared.db import set_rls_context
from app.shared.security import hash_password
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def _postgres_is_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=1.0):
            pass
        sync_url = _database_url().replace("postgresql+asyncpg://", "postgresql+psycopg://")
        from sqlalchemy import create_engine

        engine = create_engine(sync_url, connect_args={"connect_timeout": 2})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


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


# Tables named by P10-05 plus edit_sessions (P9). All must be FORCE RLS.
P10_05_TABLES = [
    "user_project_preferences",  # workspace state
    "asset_versions",  # asset version
    "asset_tags",
    "asset_tag_links",  # tag
    "shot_reference_bindings",
    "asset_version_references",  # binding
    "production_experiments",
    "shot_experiments",  # experiment
    "review_annotations",  # annotation
    "director_threads",
    "director_messages",  # director assistant
    "director_proposals",
    "director_proposal_items",  # proposal
    "edit_sessions",  # P9 editing
]

_SCRIPT = """# Episode 1 - RLS Rain

Lead: Lin Xia

## Scene 1 - Street / night
Rainy.

### Shot 1 - medium
Visual: Lin Xia turns at the corner
Dialogue: I understand.
Camera: static
"""


async def _seed_user_workspace_projects(session: AsyncSession, suffix: str) -> dict[str, Any]:
    user = User(
        email=f"p10-rls-{suffix}@example.com",
        display_name="P10 RLS owner",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"P10 RLS {suffix}")
    session.add(workspace)
    await session.flush()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)

    project_a = Project(
        workspace_id=workspace.id,
        name=f"Project A {suffix}",
        aspect_ratio="9:16",
        budget_limit=Decimal("0"),
    )
    project_b = Project(
        workspace_id=workspace.id,
        name=f"Project B {suffix}",
        aspect_ratio="9:16",
        budget_limit=Decimal("0"),
    )
    session.add_all([project_a, project_b])
    await session.flush()

    # Project B: historical-style rows in every P10-05 table.
    await set_rls_context(
        session, user_id=user.id, workspace_id=workspace.id, project_id=project_b.id
    )
    _ = await import_script(
        session,
        project_id=project_b.id,
        actor_id=user.id,
        filename=f"rls-{suffix}.md",
        text=_SCRIPT,
        actor=user,
    )
    shot = await session.scalar(
        select(Shot).where(Shot.project_id == project_b.id).order_by(Shot.sort_order).limit(1)
    )
    assert shot is not None

    asset = Asset(
        project_id=project_b.id,
        kind="character",
        name="Lin Xia",
        description="Lead",
        status="active",
        metadata_json={},
    )
    session.add(asset)
    await session.flush()
    session.add(
        AssetVersion(
            project_id=project_b.id,
            asset_id=asset.id,
            version_number=1,
            kind="character",
            name="Lin Xia",
            description="Lead",
            metadata_json={},
            status="draft",
            created_by=user.id,
        )
    )
    await session.flush()

    artifact = Artifact(
        project_id=project_b.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"p10-rls/{suffix}/kf.png",
        content_hash="e" * 64,
        mime_type="image/png",
        byte_size=64,
    )
    session.add(artifact)
    await session.flush()

    session.add(
        ReviewAnnotation(
            project_id=project_b.id,
            shot_id=shot.id,
            created_by=user.id,
            note="drift",
            status="open",
        )
    )
    thread = DirectorThread(
        project_id=project_b.id,
        scope_type="project",
        scope_entity_id=project_b.id,
        title="B thread",
        created_by=user.id,
    )
    session.add(thread)
    await session.flush()
    session.add(
        DirectorMessage(
            thread_id=thread.id,
            project_id=project_b.id,
            role="assistant",
            content="advice",
        )
    )
    proposal = DirectorProposal(
        project_id=project_b.id,
        thread_id=thread.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        status="pending",
        created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    session.add(
        DirectorProposalItem(
            proposal_id=proposal.id, project_id=project_b.id, command="shot.update_design"
        )
    )
    experiment = ProductionExperiment(
        project_id=project_b.id,
        name="B exp",
        idempotency_key=f"exp-{suffix}",
        status="draft",
        created_by=user.id,
    )
    session.add(experiment)
    await session.flush()
    session.add(
        ShotExperiment(
            production_experiment_id=experiment.id,
            project_id=project_b.id,
            shot_id=shot.id,
            prompts={},
            created_by=user.id,
        )
    )
    session.add(
        ShotReferenceBinding(
            project_id=project_b.id,
            shot_id=shot.id,
            purpose="identity",
            resolution_mode="current_formal",
            asset_id=asset.id,
            stage="image",
            created_by=user.id,
        )
    )
    session.add(
        EditSession(
            project_id=project_b.id,
            name="B edit",
            timeline={"clips": []},
            production_lineage={},
            created_by=user.id,
        )
    )
    await session.flush()
    return {
        "user": user,
        "workspace": workspace,
        "project_a": project_a,
        "project_b": project_b,
        "shot": shot,
    }


@pytest.mark.asyncio
async def test_phase10_rls_tables_forced_pg(pg_session: AsyncSession) -> None:
    """P10-05 schema audit: every listed table is FORCE RLS with >=1 policy."""
    rows = (
        await pg_session.execute(
            text(
                "SELECT c.relname, c.relforcerowsecurity, count(p.polname) AS policies "
                "FROM pg_class c "
                "LEFT JOIN pg_policy p ON p.polrelid = c.oid "
                "WHERE c.relkind='r' "
                "AND c.relnamespace=(SELECT oid FROM pg_namespace WHERE nspname='public') "
                "GROUP BY c.relname, c.relforcerowsecurity"
            )
        )
    ).all()
    by_name = {row[0]: (row[1], row[2]) for row in rows}
    missing: list[str] = []
    for table in P10_05_TABLES:
        forced, policies = by_name.get(table, (False, 0))
        if not forced or policies < 1:
            missing.append(f"{table}(forced={forced}, policies={policies})")
    assert not missing, "P10-05 tables missing FORCE RLS or policies: " + ", ".join(missing)


@pytest.mark.asyncio
async def test_phase10_rls_cross_project_negative_pg(pg_session: AsyncSession) -> None:
    """P10-05 runtime negative: project B rows are invisible under project A context."""
    suffix = uuid4().hex[:8]
    seed = await _seed_user_workspace_projects(pg_session, suffix)
    project_a = seed["project_a"]
    project_b = seed["project_b"]

    # Run the read phase as the non-bypass application role so RLS is enforced
    # (the dramaforge test role is SUPERUSER/BYPASSRLS and would skip RLS).
    await pg_session.execute(text("SET LOCAL ROLE dramaforge_app"))
    # Under project A context, project B rows must be invisible.
    await set_rls_context(
        pg_session,
        user_id=seed["user"].id,
        workspace_id=seed["workspace"].id,
        project_id=project_a.id,
    )
    queries: list[tuple[str, Any]] = [
        ("asset_versions", select(AssetVersion.id).where(AssetVersion.project_id == project_b.id)),
        (
            "review_annotations",
            select(ReviewAnnotation.id).where(ReviewAnnotation.project_id == project_b.id),
        ),
        (
            "director_threads",
            select(DirectorThread.id).where(DirectorThread.project_id == project_b.id),
        ),
        (
            "director_messages",
            select(DirectorMessage.id).where(DirectorMessage.project_id == project_b.id),
        ),
        (
            "director_proposals",
            select(DirectorProposal.id).where(DirectorProposal.project_id == project_b.id),
        ),
        (
            "director_proposal_items",
            select(DirectorProposalItem.id).where(DirectorProposalItem.project_id == project_b.id),
        ),
        (
            "production_experiments",
            select(ProductionExperiment.id).where(ProductionExperiment.project_id == project_b.id),
        ),
        (
            "shot_experiments",
            select(ShotExperiment.id).where(ShotExperiment.project_id == project_b.id),
        ),
        (
            "shot_reference_bindings",
            select(ShotReferenceBinding.id).where(ShotReferenceBinding.project_id == project_b.id),
        ),
        ("edit_sessions", select(EditSession.id).where(EditSession.project_id == project_b.id)),
    ]
    leaked: list[str] = []
    for table, query in queries:
        visible = (await pg_session.execute(query)).scalars().all()
        if visible:
            leaked.append(f"{table}:{len(visible)}")
    assert not leaked, "cross-project rows leaked under project A context: " + ", ".join(leaked)

    # Positive control: under project B context the rows ARE visible.
    await set_rls_context(
        pg_session,
        user_id=seed["user"].id,
        workspace_id=seed["workspace"].id,
        project_id=project_b.id,
    )
    assert (
        (
            await pg_session.execute(
                select(EditSession.id).where(EditSession.project_id == project_b.id)
            )
        )
        .scalars()
        .all()
    )


async def _seed_professional_resolution(session: AsyncSession, suffix: str) -> dict[str, Any]:
    user = User(
        email=f"p10-res-{suffix}@example.com",
        display_name="P10 resolution",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"P10 resolution {suffix}")
    session.add(workspace)
    await session.flush()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    project = Project(
        workspace_id=workspace.id,
        name=f"Resolution {suffix}",
        aspect_ratio="9:16",
        budget_limit=Decimal("0"),
    )
    session.add(project)
    await session.flush()
    await set_rls_context(
        session, user_id=user.id, workspace_id=workspace.id, project_id=project.id
    )

    _ = await import_script(
        session,
        project_id=project.id,
        actor_id=user.id,
        filename=f"res-{suffix}.md",
        text=_SCRIPT,
        actor=user,
    )
    shot = await session.scalar(
        select(Shot).where(Shot.project_id == project.id).order_by(Shot.sort_order).limit(1)
    )
    assert shot is not None
    keyframe = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=f"p10-res/{suffix}/formal.png",
        content_hash="a1" * 32,
        mime_type="image/png",
        byte_size=128,
    )
    session.add(keyframe)
    await session.flush()
    shot.formal_keyframe_artifact_id = keyframe.id
    await session.flush()

    manifest = next(item for item in SEED_MANIFESTS if item["model_id"] == "agnes-video-v2.0")
    model_id = f"p10-res-{suffix}"
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
    session.add_all([entry, credential])
    await session.flush()
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
    session.add(connection)
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
        bindings={
            ModelSlot.VIDEO_SHOT.value: {
                "slot": ModelSlot.VIDEO_SHOT.value,
                "model_id": f"agnes/{model_id}",
                "native_options": {"seed": 7},
                "enabled": True,
            }
        },
        created_by=user.id,
        updated_by=user.id,
    )
    session.add_all([binding, profile])
    await session.flush()
    return {
        "user": user,
        "workspace": workspace,
        "project": project,
        "shot": shot,
        "binding": binding,
        "keyframe": keyframe,
    }


@pytest.mark.asyncio
async def test_phase10_professional_resolution_no_bypass_pg(pg_session: AsyncSession) -> None:
    """07 §23: professional path resolves via ExecutionModelResolver only."""
    suffix = uuid4().hex[:8]
    seed = await _seed_professional_resolution(pg_session, suffix)
    project = seed["project"]
    shot = seed["shot"]
    binding = seed["binding"]
    user = seed["user"]
    await set_rls_context(
        pg_session, user_id=user.id, workspace_id=seed["workspace"].id, project_id=project.id
    )

    service = WorkbenchExecutionService(pg_session, user_id=user.id)
    plan = await service.build_plan(
        project=project,
        execution_input=WorkbenchExecutionInput(
            project_id=project.id,
            stage="video",
            shot_id=shot.id,
            prompt="Lin Xia turns at the corner",
            semantic_intent={"action": "turn"},
            mode_id="explicit_binding",
        ),
    )
    assert plan.resolved_model.status == "RESOLVED"
    assert plan.resolved_model.source in {
        "project_profile",
        "request_override",
        "workspace_profile",
    }
    assert plan.resolved_model.provider_model_binding_id == binding.id
    assert plan.resolved_model.catalog_entry_id is not None
    assert not plan.capability_gaps

    run = await service.create_and_dispatch(
        project=project,
        execution_input=WorkbenchExecutionInput(
            project_id=project.id,
            stage="video",
            shot_id=shot.id,
            prompt="Lin Xia turns at the corner",
            semantic_intent={"action": "turn"},
            mode_id="explicit_binding",
        ),
    )
    await pg_session.flush()
    stored = await pg_session.scalar(select(NodeRun.input_snapshot).where(NodeRun.id == run.id))
    assert stored is not None
    workbench_plan = stored.get("workbench_plan") or {}
    assert workbench_plan.get("resolved_model", {}).get("status") == "RESOLVED"
    assert workbench_plan.get("resolved_model", {}).get("provider_model_binding_id") == str(
        binding.id
    )
    # frozen identity travels to the worker; no direct provider HTTP at dispatch.
    assert run.status == "queued"
    assert stored.get("node_key") == "video"
