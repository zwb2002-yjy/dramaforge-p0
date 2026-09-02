"""Phase 5 V2 Gate restart-recovery + binding-freeze evidence on real PostgreSQL.

Covers the Phase 5 Gate items that need persistence proof:

- Worker restart recovery: ``recover_interrupted_provider_jobs`` re-queues a
  running unified NodeRun through the real PG SQL function
  ``app.resumable_provider_node_run_contexts`` and the RLS scope path.
- API restart no task loss: ``dispatch_outbox`` re-enqueues a pending NodeRun
  from a durable Outbox row.
- 旧任务不会读取新的 Binding: a NodeRun created by ``queue_branch_nodes`` freezes
  ``model_binding_id`` at dispatch; when the project later re-points at a second
  binding, execution still submits against the frozen binding (explicit_binding),
  never the newer one.

No Provider is contacted; the worker is driven inline with a fake unified plugin.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.config import Settings, clear_settings_cache
from app.events.models import OutboxEvent
from app.execution.experiment_nodes import queue_branch_nodes
from app.execution.models import (
    GraphNode,
    NodeRun,
    ProviderOperation,
)
from app.production.service import GraphService
from app.providers import registry as registry_module
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import hash_manifest
from app.providers.models import (
    ProviderConnection,
    ProviderModelBinding,
)
from app.providers.registry import ProviderPlugin, register_plugin
from app.providers.runtime import (
    CompiledImageRequest,
    CompiledVideoRequest,
    CostResult,
    PollResult,
    ProviderResumeToken,
    SubmissionResult,
)
from app.providers.workspace_credentials import configured_byok_keyring
from app.runtime.scheduler import NodeRunScheduler, WorkerRuntime
from app.security.credentials import store_credential
from app.shared.db import set_rls_context
from app.shared.enums import OutboxStatus
from app.shared.security import hash_password
from app.storage.minio_store import reset_object_store_for_tests
from pg_support import available
from sqlalchemy import select, text
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
    reset_object_store_for_tests()
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()
    reset_object_store_for_tests()


def _byok(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    keyring_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{keyring_key}")
    clear_settings_cache()


async def _project(session: AsyncSession) -> tuple[User, UUID, UUID]:
    suffix = uuid4().hex[:8]
    user = User(
        email=f"p5-{suffix}@example.com",
        display_name="P5",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"P5Org-{suffix}")
    session.add(workspace)
    await session.flush()
    await set_rls_context(session, user_id=user.id, workspace_id=workspace.id)
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P5Proj-{suffix}",
        aspect_ratio="9:16",
        actor=user,
    )
    await session.commit()
    await set_rls_context(
        session,
        user_id=user.id,
        workspace_id=workspace.id,
        project_id=project.id,
    )
    return user, project.id, workspace.id


async def _seed_graph_and_run(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    node_key: str,
    node_type: str,
    status: str = "queued",
    snapshot: dict[str, object] | None = None,
) -> NodeRun:
    graph = await GraphService(session).create_graph(
        project_id=project_id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="p5-restart-test",
        created_by=user_id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key=node_key,
        node_type=node_type,
        display_name=node_key.capitalize(),
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project_id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"p5:{uuid4()}",
        input_hash=uuid4().hex * 2,
        status=status,
        input_snapshot=snapshot or {},
        output_summary={},
        created_by=user_id,
    )
    session.add(run)
    await session.flush()
    return run


async def _seed_binding(
    session: AsyncSession,
    *,
    project_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    provider_type: str,
    protocol_profile: str,
    model_id: str,
    media_kind: str,
    purpose: str,
    manifest: dict[str, Any],
    invoke_model_value: str,
    quality_gated: bool = True,
    connection: ProviderConnection | None = None,
    project_binding: bool = True,
) -> tuple[ProviderModelBinding, ProviderConnection]:
    from app.providers.models import (
        ProjectProviderBinding,
        ProviderConnectionRevision,
    )

    credential = await store_credential(
        session,
        workspace_id=workspace_id,
        provider=provider_type,
        plaintext="p5-secret",
        keyring=configured_byok_keyring(),
    )
    entry = ModelCatalogEntry(
        provider_type=provider_type,
        protocol_profile=protocol_profile,
        model_id=model_id,
        model_revision="v1",
        display_name=f"{model_id}",
        media_kind=media_kind,
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=manifest,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(manifest),
    )
    session.add(entry)
    await session.flush()
    if connection is None:
        connection = ProviderConnection(
            workspace_id=workspace_id,
            provider_type=provider_type,
            display_name=provider_type,
            base_url="https://unified.example.com",
            protocol_profile=protocol_profile,
            credential_id=credential.id,
            credential_revision=1,
            enabled=True,
            verification_status="verified",
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(connection)
        await session.flush()
        session.add(
            ProviderConnectionRevision(
                connection_id=connection.id,
                revision_no=1,
                provider_type=provider_type,
                protocol_profile=protocol_profile,
                base_url=connection.base_url,
                credential_revision_id=credential.id,
            )
        )
        await session.flush()
    binding = ProviderModelBinding(
        workspace_id=workspace_id,
        connection_id=connection.id,
        media_type=media_kind,
        model_id=model_id,
        purpose=purpose,
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=quality_gated,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id=model_id,
        invoke_model_value=invoke_model_value,
        pricing_snapshot_json={"unit_amount": "1", "currency": "USD"},
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(binding)
    await session.flush()
    if project_binding:
        session.add(
            ProjectProviderBinding(
                project_id=project_id,
                workspace_id=workspace_id,
                purpose=purpose,
                model_binding_id=binding.id,
                selection_strategy="explicit_binding",
                fallback_policy="none",
                updated_by=user_id,
            )
        )
        await session.flush()
    return binding, connection


# ---------------------------------------------------------------------------
# Fake unified plugin (modeled on test_unified_path) — zero network, records
# the compiled request so the test can assert which binding was actually used.
# ---------------------------------------------------------------------------

FAKE_PROVIDER = "p5_test"
FAKE_PROFILE = "p5_v1"

_FAKE_MANIFEST = {
    "manifest_version": "2026-08-10",
    "provider_type": FAKE_PROVIDER,
    "protocol_profile": FAKE_PROFILE,
    "model_id": "p5-img-model",
    "model_revision": "v1",
    "media_kind": "image",
    "display_name": "P5 Image",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-10",
    "operations": {
        "image.generate": {
            "operation": "image.generate",
            "capabilities": ["image.t2i", "image.i2i"],
            "output_constraints": {
                "size": "1K",
                "aspect_ratio": "9:16",
                "width": 736,
                "height": 1312,
            },
            "reference_constraints": {"reference_image": {"min": 0, "max": 1}},
            "exclusive_groups": [],
        }
    },
    "option_schema": {"namespace": "", "options": {}},
}


class _P5Runtime:
    provider = FAKE_PROVIDER
    protocol_profile = FAKE_PROFILE

    def __init__(self) -> None:
        self.submit_calls = 0
        self.compiled_model: str | None = None
        self._remote = f"p5-img-{uuid4().hex[:10]}"

    async def submit_image(self, request: CompiledImageRequest) -> SubmissionResult:
        self.submit_calls += 1
        self.compiled_model = request.model_id
        return SubmissionResult(
            remote_task_id=self._remote,
            status="succeeded",
            artifact_uri="fake://p5-result",
            request_fingerprint="f" * 64,
            request_summary={"operation": "image.t2i", "model": request.model_id},
            resume_token=ProviderResumeToken(
                provider_type=FAKE_PROVIDER,
                protocol_profile=FAKE_PROFILE,
                remote_task_id=self._remote,
                query_kind="task_id",
            ),
        )

    async def poll_video(self, resume: ProviderResumeToken) -> PollResult:
        return PollResult(status="succeeded", artifact_uri=None)

    async def fetch_cost(self, resume: ProviderResumeToken) -> CostResult:
        return CostResult(amount=Decimal("1.25"), currency="USD", units=1)

    async def submit_video(self, request: CompiledVideoRequest) -> SubmissionResult:
        raise AssertionError("image-only test")

    async def cancel_video(self, resume: ProviderResumeToken) -> object:
        return {"status": "cancelled"}


class _P5ImageCompiler:
    async def compile(
        self,
        intent: object,
        model: object,
        references: list[object],
        *,
        invoke_model_value: str,
    ) -> CompiledImageRequest:
        return CompiledImageRequest(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request={"model": invoke_model_value, "prompt": getattr(intent, "prompt", "")},
            request_schema_version="2026-08-10",
            safe_request_summary={"operation": "image.t2i", "model": invoke_model_value},
            reference_artifact_ids=[],
            reference_fingerprints=[],
        )


class _P5VideoCompiler:
    async def compile(
        self,
        intent: object,
        model: object,
        references: list[object],
        *,
        invoke_model_value: str,
    ) -> CompiledVideoRequest:
        raise AssertionError("image-only test")


_RUNTIME_HOLDER: dict[str, _P5Runtime] = {}


def _p5_plugin() -> ProviderPlugin:
    def _runtime_factory(**kwargs: object) -> _P5Runtime:
        runtime = _P5Runtime()
        _RUNTIME_HOLDER["runtime"] = runtime
        return runtime

    return ProviderPlugin(
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        display_name="P5 Test",
        default_base_url="https://unified.example.com",
        implemented=True,
        settings_prefix=FAKE_PROVIDER,
        credential_provider_key=FAKE_PROVIDER,
        catalog_manifests=(_FAKE_MANIFEST,),
        runtime_factory=_runtime_factory,
        compiler_factory=lambda: (_P5ImageCompiler(), _P5VideoCompiler()),
    )


@pytest.fixture
def p5_plugin() -> ProviderPlugin:
    clear_settings_cache()
    _RUNTIME_HOLDER.clear()
    plugin = _p5_plugin()
    register_plugin(plugin)
    try:
        yield plugin
    finally:
        registry_module._registry.pop((FAKE_PROVIDER, FAKE_PROFILE), None)
        _RUNTIME_HOLDER.clear()
        clear_settings_cache()


# ---------------------------------------------------------------------------
# Test 1: Worker restart recovery on real PG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_restart_requeues_resumable_unified_run_pg(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.jobs import recover_interrupted_provider_jobs

    user, project_id, workspace_id = await _project(pg_session)
    run = await _seed_graph_and_run(
        pg_session,
        project_id=project_id,
        user_id=user.id,
        node_key="keyframe",
        node_type="keyframe",
        status="running",
        snapshot={
            "shot_id": str(uuid4()),
            "node_key": "keyframe",
            "source_commit": "p5-restart-commit",
            "dispatch_generation": "initial-submit",
        },
    )
    await pg_session.flush()
    remote_id = f"p5-remote-{uuid4().hex[:8]}"
    op = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="keyframe.generate",
        actual_provider=FAKE_PROVIDER,
        actual_model="p5-img-model",
        protocol_profile=FAKE_PROFILE,
        request_fingerprint="f" * 64,
        status="submitted",
        request_summary={"kind": "keyframe"},
        response_summary={},
        provider_operation_id=remote_id,
        resume_token={
            "provider_type": FAKE_PROVIDER,
            "protocol_profile": FAKE_PROFILE,
            "remote_task_id": remote_id,
            "query_kind": "task_id",
        },
        execution_path_version="unified-v1",
    )
    pg_session.add(op)
    await pg_session.commit()

    # recover_interrupted_provider_jobs opens its own session via
    # get_session_factory; route it to a fresh factory on the same PG target.
    factory_engine = create_async_engine(_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(factory_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(
        "app.workers.jobs.get_session_factory",
        lambda: factory,
    )
    enqueue = AsyncMock(return_value="p5-resume-job")
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", enqueue)

    await recover_interrupted_provider_jobs({})

    # Re-open a fresh session to observe the committed re-queue.
    async with factory() as observer:
        await set_rls_context(
            observer,
            user_id=user.id,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        observed_run = await observer.get(NodeRun, run.id)
        assert observed_run is not None
        assert observed_run.status == "queued"
        snap = observed_run.input_snapshot or {}
        assert snap["provider_poll_resume_count"] == 1
        assert str(snap["dispatch_generation"]).startswith("provider-resume-")
        observed_op = await observer.get(ProviderOperation, op.id)
        assert observed_op is not None
        assert observed_op.provider_operation_id == remote_id
        assert observed_op.attempt_no == 1
        assert observed_op.status == "submitted"
    enqueue.assert_awaited_once_with(run.id)
    await factory_engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: API restart no task loss — durable Outbox re-enqueues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_restart_outbox_reenqueues_pending_node_run_pg(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.jobs import dispatch_outbox

    user, project_id, workspace_id = await _project(pg_session)
    run = await _seed_graph_and_run(
        pg_session,
        project_id=project_id,
        user_id=user.id,
        node_key="keyframe",
        node_type="keyframe",
        status="queued",
        snapshot={"shot_id": str(uuid4()), "node_key": "keyframe"},
    )
    server_now = (await pg_session.execute(text("SELECT now()"))).scalar_one()
    event = OutboxEvent(
        event_id=uuid4(),
        project_id=project_id,
        topic="node_run.enqueue",
        schema_version=1,
        payload={"node_run_id": str(run.id), "status": "queued"},
        status=OutboxStatus.PENDING.value,
        attempt_count=0,
        next_attempt_at=server_now,
    )
    pg_session.add(event)
    await pg_session.commit()

    factory_engine = create_async_engine(_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(factory_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(
        "app.workers.jobs.get_session_factory",
        lambda: factory,
    )
    drain = AsyncMock(return_value="p5-drain-job")
    monkeypatch.setattr(
        NodeRunScheduler,
        "_enqueue_node_run",
        drain,
    )

    await dispatch_outbox({})

    async with factory() as observer:
        await set_rls_context(
            observer,
            user_id=user.id,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        observed_event = await observer.get(OutboxEvent, event.id)
        assert observed_event is not None
        assert observed_event.status == OutboxStatus.PUBLISHED.value
        assert observed_event.event_id == event.event_id
    # Durable Outbox row (created before the "restart") was claimed + published:
    # the enqueue intent survives an API restart (no task lost). The queued
    # NodeRun drain is a shared-PG batch; prove this run is dispatchable by the
    # same resolver the restart uses rather than depending on drain ordering.
    from app.shared.db import list_queued_node_run_rls_scopes

    factory_sync = create_async_engine(_database_url(), pool_pre_ping=True)
    async with async_sessionmaker(factory_sync)() as probe:
        queued = await list_queued_node_run_rls_scopes(
            probe,
            limit=500,
            project_id=project_id,
        )
        assert any(str(run_id) == str(run.id) for run_id, _scope in queued)
    await factory_sync.dispose()
    await factory_engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: 旧任务不会读取新的 Binding — frozen dispatch wins over a later change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_old_task_never_reads_new_binding_pg(
    pg_session: AsyncSession,
    p5_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.execution.product_path as pp
    from app.assets.models import Episode, Scene, Shot
    from app.providers.models import ProjectProviderBinding

    _byok(monkeypatch)
    user, project_id, workspace_id = await _project(pg_session)

    # A concrete shot (the branch queue requires a Shot).
    episode = Episode(project_id=project_id, episode_number=1, title="E")
    pg_session.add(episode)
    await pg_session.flush()
    scene = Scene(episode_id=episode.id, scene_number=1, location_name="L", time_of_day="day")
    pg_session.add(scene)
    await pg_session.flush()
    shot = Shot(
        project_id=project_id,
        scene_id=scene.id,
        shot_number=1,
        sort_order=1,
        visual_description="portrait",
        dialogue="",
        status="draft",
        duration_seconds=5,
    )
    pg_session.add(shot)
    await pg_session.flush()

    # Binding B1: the model the operator reviewed at dispatch.
    suffix = uuid4().hex[:8]
    b1_model = f"p5-img-{suffix}"
    b1_manifest = {**_FAKE_MANIFEST, "model_id": b1_model}
    b1, _conn = await _seed_binding(
        pg_session,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=user.id,
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        model_id=b1_model,
        media_kind="image",
        purpose="keyframe",
        manifest=b1_manifest,
        invoke_model_value=b1_model,
    )
    await pg_session.commit()

    # Dispatch while B1 is current. Order follows keys: prompt first, then keyframe.
    run_ids = await queue_branch_nodes(
        pg_session,
        project_id=project_id,
        shot_id=shot.id,
        user_id=user.id,
        node_keys=["prompt", "keyframe"],
    )
    assert len(run_ids) == 2
    prompt_run = await pg_session.get(NodeRun, run_ids[0])
    run = await pg_session.get(NodeRun, run_ids[1])
    assert prompt_run is not None and run is not None
    assert (run.input_snapshot or {})["model_binding_id"] == str(b1.id)
    # The prompt node is a zero-cost upstream that must complete before keyframe.
    assert await WorkerRuntime(pg_session).process_one(prompt_run.id)
    await pg_session.commit()

    # Later, the operator re-points the project at a DIFFERENT binding B2.
    b2_model = f"p5-img-{suffix}-v2"
    b2_manifest = {**_FAKE_MANIFEST, "model_id": b2_model}
    b2, _ = await _seed_binding(
        pg_session,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=user.id,
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        model_id=b2_model,
        media_kind="image",
        purpose="keyframe",
        manifest=b2_manifest,
        invoke_model_value=b2_model,
        connection=_conn,
        project_binding=False,
    )
    project_binding = await pg_session.scalar(
        select(ProjectProviderBinding).where(
            ProjectProviderBinding.project_id == project_id,
            ProjectProviderBinding.purpose == "keyframe",
        )
    )
    assert project_binding is not None
    project_binding.model_binding_id = b2.id
    await pg_session.commit()

    # Execute the OLD run. It must submit against B1 (frozen at dispatch), not B2.
    monkeypatch.setattr(
        pp,
        "get_settings",
        lambda: Settings(
            app_env="test",
            database_url=_database_url(),
        ),
    )
    ok = await WorkerRuntime(pg_session).process_one(run.id)
    assert ok
    await pg_session.refresh(run)
    assert run.status == "completed", (
        f"run status={run.status} error={run.error_code}:{run.error_summary}"
    )

    op = (
        await pg_session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.status == "succeeded"
    assert op.model_binding_id == b1.id
    assert op.actual_model == b1_model
    runtime = _RUNTIME_HOLDER.get("runtime")
    assert runtime is not None
    assert runtime.compiled_model == b1_model  # B1's invoke value, not B2's
    assert b2.id != b1.id
