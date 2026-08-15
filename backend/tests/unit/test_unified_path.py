"""Stage B4 unified execution path tests: single-path submission, resume-no-
recreate, submission_started crash semantics, and unbound fail-closed.

A fake provider plugin rides the whole unified chain (selection -> compiler ->
runtime) with zero network, proving the path works without a provider branch.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.config import Settings, clear_settings_cache
from app.creation import models as _cm  # noqa: F401
from app.director.execution_guard import DirectorExecutionGuardError
from app.director.models import (
    BudgetAuthorization,
    BudgetReservation,
    DirectorWorkflowRun,
    ProductionBatch,
)
from app.execution import models as _xm  # noqa: F401
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun, ProviderOperation
from app.execution.product_path import (
    UNIFIED_PATH_VERSION,
    execute_media_node_run,
)
from app.production import models as _pm  # noqa: F401
from app.production.service import GraphService
from app.providers import registry as registry_module
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import hash_manifest
from app.providers.models import (
    ProjectProviderBinding,
    ProviderConnection,
    ProviderModelBinding,
)
from app.providers.registry import ProviderPlugin, register_plugin
from app.providers.runtime import (
    CancelResult,
    CompiledImageRequest,
    CompiledVideoRequest,
    CostResult,
    PollResult,
    ProviderResumeToken,
    SubmissionResult,
)
from app.providers.workspace_credentials import configured_byok_keyring
from app.security.credentials import store_credential
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

FAKE_PROVIDER = "unified_test"
FAKE_PROFILE = "u_test_v1"

# Test-scoped behavior plan for submit_image outcomes ("PROVIDER_RATE_LIMITED"
# marks one submission as a 429; anything else = success).
_FAKE_IMAGE_PLAN: list[str] = []


_FAKE_IMAGE_MANIFEST = {
    "manifest_version": "2026-08-10",
    "provider_type": FAKE_PROVIDER,
    "protocol_profile": FAKE_PROFILE,
    "model_id": "uni-img-model",
    "model_revision": "v1",
    "media_kind": "image",
    "display_name": "Unified Image",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-10",
    "operations": {
        "image.generate": {
            "operation": "image.generate",
            "capabilities": ["image.t2i", "image.i2i"],
            "output_constraints": {},
            "reference_constraints": {"reference_image": {"min": 0, "max": 1}},
            "exclusive_groups": [],
        }
    },
    "option_schema": {"namespace": "", "options": {}},
}

_FAKE_VIDEO_MANIFEST = {
    "manifest_version": "2026-08-10",
    "provider_type": FAKE_PROVIDER,
    "protocol_profile": FAKE_PROFILE,
    "model_id": "uni-vid-model",
    "model_revision": "v1",
    "media_kind": "video",
    "display_name": "Unified Video",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-10",
    "operations": {
        "video.generate": {
            "operation": "video.generate",
            "capabilities": ["video.i2v.first_frame"],
            "output_constraints": {
                "aspect_ratio": "16:9",
                "duration_seconds": {"allowed": [6]},
                "native_audio": False,
            },
            "reference_constraints": {"first_frame": {"min": 1, "max": 1}},
            "exclusive_groups": [],
        }
    },
    "option_schema": {"namespace": "", "options": {}},
}


class FakeUnifiedRuntime:
    provider = FAKE_PROVIDER
    protocol_profile = FAKE_PROFILE

    def __init__(self) -> None:
        self.submit_calls = 0
        self.poll_calls = 0
        self.submitted_image: CompiledImageRequest | None = None
        self.submitted_video: CompiledVideoRequest | None = None

    def _token(self, remote: str) -> ProviderResumeToken:
        return ProviderResumeToken(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            remote_task_id=remote,
            query_kind="task_id",
        )

    async def submit_image(self, request: CompiledImageRequest) -> SubmissionResult:
        self.submit_calls += 1
        self.submitted_image = request
        remote = "uni-img-1"
        if _FAKE_IMAGE_PLAN:
            code = _FAKE_IMAGE_PLAN.pop(0)
            if code == "PROVIDER_RATE_LIMITED":
                return SubmissionResult(
                    status="failed",
                    error_code=code,
                    error="rate limited",
                    retry_after_seconds=5.0,
                    request_fingerprint="f" * 64,
                    request_summary={"operation": "image.t2i", "model": "uni-img-model"},
                )
        return SubmissionResult(
            remote_task_id=remote,
            status="succeeded",
            artifact_uri="fake://image-result",
            request_fingerprint="f" * 64,
            request_summary={"operation": "image.t2i", "model": "uni-img-model"},
            resume_token=self._token(remote),
        )

    async def submit_video(self, request: CompiledVideoRequest) -> SubmissionResult:
        self.submit_calls += 1
        self.submitted_video = request
        remote = "uni-vid-1"
        return SubmissionResult(
            remote_task_id=remote,
            status="queued",
            query_kind="task_id",
            request_fingerprint="f" * 64,
            request_summary={"operation": "video.i2v", "model": "uni-vid-model"},
            resume_token=self._token(remote),
        )

    async def poll_video(self, resume: ProviderResumeToken) -> PollResult:
        self.poll_calls += 1
        return PollResult(status="succeeded", artifact_uri=None)

    async def cancel_video(self, resume: ProviderResumeToken) -> CancelResult:
        return CancelResult(status="cancelled")

    async def fetch_cost(self, resume: ProviderResumeToken) -> CostResult:
        return CostResult(amount=1.25, currency="USD", units=1.0)


class FakeUnifiedImageCompiler:
    def validate(self, intent: object, model: object) -> None:
        return None

    async def compile(
        self,
        intent: object,
        model: object,
        references: list[object],
        *,
        invoke_model_value: str,
    ) -> CompiledImageRequest:
        reference_ids = [str(ref.artifact_id) for ref in references]
        fingerprints = [
            str(ref.fingerprint) for ref in references if getattr(ref, "fingerprint", None)
        ]
        return CompiledImageRequest(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request={
                "model": invoke_model_value,
                "prompt": getattr(intent, "prompt", ""),
                "size": getattr(intent, "size", None),
                "reference_artifact_ids": reference_ids,
            },
            request_schema_version="2026-08-10",
            safe_request_summary={
                "operation": "image.i2i" if reference_ids else "image.t2i",
                "size": getattr(intent, "size", None),
                "reference_artifact_ids": reference_ids,
                "reference_fingerprints": fingerprints,
            },
            reference_artifact_ids=[ref.artifact_id for ref in references],
            reference_fingerprints=fingerprints,
        )


class FakeUnifiedVideoCompiler:
    def validate(self, intent: object, model: object) -> None:
        return None

    async def compile(
        self,
        intent: object,
        model: object,
        references: list[object],
        *,
        invoke_model_value: str,
    ) -> CompiledVideoRequest:
        first_frame = next(ref for ref in references if ref.role == "first_frame")
        output = intent.output
        aspect_ratio = output.aspect_ratio
        duration_seconds = output.duration_seconds
        generate_audio = output.generate_audio
        if aspect_ratio != "16:9" or duration_seconds != 6 or generate_audio is not False:
            raise ValueError("test provider rejected an incomplete Director video request")
        fingerprints = [str(first_frame.fingerprint)] if first_frame.fingerprint else []
        return CompiledVideoRequest(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            model_id=invoke_model_value,
            operation="video.generate",
            wire_request={
                "model": invoke_model_value,
                "prompt": getattr(intent, "prompt", ""),
                "first_frame_artifact_id": str(first_frame.artifact_id),
                "aspect_ratio": aspect_ratio,
                "duration_seconds": duration_seconds,
                "generate_audio": generate_audio,
            },
            request_schema_version="2026-08-10",
            safe_request_summary={
                "operation": "video.i2v",
                "aspect_ratio": aspect_ratio,
                "duration_seconds": duration_seconds,
                "native_audio": generate_audio,
                "reference_artifact_ids": [str(first_frame.artifact_id)],
                "reference_fingerprints": fingerprints,
            },
            reference_artifact_ids=[ref.artifact_id for ref in references],
            reference_fingerprints=fingerprints,
        )


_FAKE_RUNTIME_HOLDER: dict[str, FakeUnifiedRuntime] = {}


def _fake_plugin() -> ProviderPlugin:
    def _runtime_factory(**kwargs: object) -> FakeUnifiedRuntime:
        runtime = FakeUnifiedRuntime()
        _FAKE_RUNTIME_HOLDER["runtime"] = runtime
        return runtime

    return ProviderPlugin(
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        display_name="Unified Test",
        default_base_url="https://unified.example.com",
        implemented=True,
        settings_prefix=FAKE_PROVIDER,
        credential_provider_key=FAKE_PROVIDER,
        catalog_manifests=(_FAKE_IMAGE_MANIFEST, _FAKE_VIDEO_MANIFEST),
        runtime_factory=_runtime_factory,
        compiler_factory=lambda: (FakeUnifiedImageCompiler(), FakeUnifiedVideoCompiler()),
    )


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    reset_object_store_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()
    reset_object_store_for_tests()


@pytest.fixture
def fake_plugin() -> ProviderPlugin:
    _FAKE_RUNTIME_HOLDER.clear()
    _FAKE_IMAGE_PLAN.clear()
    plugin = _fake_plugin()
    register_plugin(plugin)
    try:
        yield plugin
    finally:
        registry_module._registry.pop((FAKE_PROVIDER, FAKE_PROFILE), None)
        _FAKE_RUNTIME_HOLDER.clear()
        _FAKE_IMAGE_PLAN.clear()


def _current_runtime() -> FakeUnifiedRuntime:
    runtime = _FAKE_RUNTIME_HOLDER.get("runtime")
    assert runtime is not None
    return runtime


def _byok(monkeypatch: pytest.MonkeyPatch) -> None:
    keyring_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("BYOK_PRIMARY_KEY_VERSION", "v1")
    monkeypatch.setenv("BYOK_KEYRING", f"v1:{keyring_key}")
    clear_settings_cache()


def _enable_unified(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.execution.product_path as pp

    monkeypatch.setattr(
        pp,
        "get_settings",
        lambda: Settings(provider_unified_path_enabled=True),
    )


async def _seed_project_chain(
    session: AsyncSession,
) -> tuple[User, Workspace, NodeRun, FakeUnifiedRuntime]:
    user = User(
        email=f"uni-{uuid4().hex}@example.com",
        display_name="Unified",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Uni-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name="Unified Path",
        aspect_ratio="9:16",
        actor=user,
    )
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="uni-test",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="Keyframe",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"uni:{uuid4()}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={
            "plan": {"prompt": "unified keyframe"},
            "lead_identity_required": False,
        },
        created_by=user.id,
    )
    session.add(run)
    await session.flush()

    await store_credential(
        session,
        workspace_id=workspace.id,
        provider=FAKE_PROVIDER,
        plaintext="uni-secret",
        keyring=configured_byok_keyring(),
    )
    entry = ModelCatalogEntry(
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        model_id="uni-img-model",
        model_revision="v1",
        display_name="Unified Image",
        media_kind="image",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=_FAKE_IMAGE_MANIFEST,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(_FAKE_IMAGE_MANIFEST),
    )
    session.add(entry)
    await session.flush()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        provider_type=FAKE_PROVIDER,
        display_name="Unified",
        base_url="https://unified.example.com",
        protocol_profile=FAKE_PROFILE,
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
        media_type="image",
        model_id="uni-img-model",
        purpose="keyframe",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="uni-img-model",
        invoke_model_value="uni-img-model",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(binding)
    await session.flush()
    session.add(
        ProjectProviderBinding(
            project_id=project.id,
            workspace_id=workspace.id,
            purpose="keyframe",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=user.id,
        )
    )
    await session.flush()
    return user, workspace, run


async def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.execution.product_path.asyncio.sleep", no_sleep)


async def _attach_director_context(
    session: AsyncSession,
    *,
    user: User,
    run: NodeRun,
    model_binding_id: object,
    purpose: str = "keyframe",
) -> ProductionBatch:
    workflow = DirectorWorkflowRun(
        project_id=run.project_id,
        template_id="live_action_dialogue_short_v1",
        template_version="1.0.0",
        status="trial_running",
        current_stage="trial",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()
    authorization = BudgetAuthorization(
        project_id=run.project_id,
        workflow_run_id=workflow.id,
        authorization_kind="trial_budget",
        idempotency_key=f"auth:{uuid4()}",
        pricing_snapshot_id="pricing-v1",
        limit_amount=Decimal("10"),
        consumed_amount=Decimal("0"),
        currency="USD",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    frozen_id = str(model_binding_id)
    batch = ProductionBatch(
        project_id=run.project_id,
        workflow_run_id=workflow.id,
        batch_kind="trial",
        idempotency_key=f"batch:{uuid4()}",
        status="running",
        budget_authorization_id=authorization.id,
        locked_version_refs={},
        selected_shot_ids=["shot-1"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={
            "plans": [{"purpose": purpose, "model_binding_id": frozen_id}]
        },
        semantic_hash="d" * 64,
        created_by=user.id,
    )
    session.add(batch)
    await session.flush()
    reservation = BudgetReservation(
        project_id=run.project_id,
        batch_id=batch.id,
        authorization_id=authorization.id,
        idempotency_key=f"reservation:{uuid4()}",
        reserved_amount=Decimal("10"),
        currency="USD",
        status="reserved",
    )
    session.add(reservation)
    await session.flush()
    run.production_batch_id = batch.id
    run.budget_reservation_id = reservation.id
    run.input_snapshot = {
        **run.input_snapshot,
        "workflow_run_id": str(workflow.id),
        "production_batch_id": str(batch.id),
        "budget_reservation_id": str(reservation.id),
        "purpose": purpose,
        "model_binding_id": frozen_id,
        "selection_plan": {
            "purpose": purpose,
            "model_binding_id": frozen_id,
        },
    }
    await session.flush()
    return batch


async def _attach_canonical_source(
    session: AsyncSession,
    *,
    user: User,
    run: NodeRun,
    batch: ProductionBatch,
) -> Artifact:
    source = NodeRun(
        project_id=run.project_id,
        graph_version_id=run.graph_version_id,
        graph_node_id=run.graph_node_id,
        production_batch_id=batch.id,
        attempt_no=1,
        idempotency_key=f"canonical:{uuid4()}",
        input_hash="c" * 64,
        status="completed",
        input_snapshot={"node_key": "character_reference", "shot_id": "shot-1"},
        created_by=user.id,
    )
    session.add(source)
    await session.flush()
    source_bytes = b"fictional-canonical-image"
    stored = await get_object_store().put_bytes(
        object_key=f"projects/{run.project_id}/canonical/{source.id}.png",
        data=source_bytes,
        mime_type="image/png",
    )
    artifact = Artifact(
        project_id=run.project_id,
        artifact_type="image",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=source.id,
    )
    session.add(artifact)
    await session.flush()
    source.result_artifact_id = artifact.id
    run.input_snapshot = {
        **run.input_snapshot,
        "canonical_source_run_id": str(source.id),
        "lead_identity_required": True,
    }
    await session.flush()
    return artifact


async def _seed_video_binding(
    session: AsyncSession,
    *,
    workspace_id: object,
    project_id: object,
    user_id: object,
) -> ProviderModelBinding:
    entry = ModelCatalogEntry(
        provider_type=FAKE_PROVIDER,
        protocol_profile=FAKE_PROFILE,
        model_id="uni-vid-model",
        model_revision="v1",
        display_name="Unified Video",
        media_kind="video",
        lifecycle="active",
        catalog_source="official_static",
        capability_manifest_json=_FAKE_VIDEO_MANIFEST,
        option_schema_json={},
        documented_at=date.fromisoformat("2026-08-10"),
        contract_manifest_hash=hash_manifest(_FAKE_VIDEO_MANIFEST),
    )
    session.add(entry)
    await session.flush()
    connection = await session.scalar(
        select(ProviderConnection).where(ProviderConnection.workspace_id == workspace_id)
    )
    assert connection is not None
    binding = ProviderModelBinding(
        workspace_id=workspace_id,
        connection_id=connection.id,
        media_type="video",
        model_id="uni-vid-model",
        purpose="video",
        enabled=True,
        documented=True,
        contract_tested=True,
        account_verified=True,
        quality_gated=True,
        catalog_entry_id=entry.id,
        capability_manifest_hash=entry.contract_manifest_hash,
        remote_resource_kind="model",
        remote_resource_id="uni-vid-model",
        invoke_model_value="uni-vid-model",
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(binding)
    await session.flush()
    session.add(
        ProjectProviderBinding(
            project_id=project_id,
            workspace_id=workspace_id,
            purpose="video",
            model_binding_id=binding.id,
            selection_strategy="explicit_binding",
            fallback_policy="none",
            updated_by=user_id,
        )
    )
    await session.flush()
    return binding


@pytest.mark.asyncio
async def test_unified_keyframe_submits_once_and_completes(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)

    result = await execute_media_node_run(session, node_run_id=run.id)
    assert result.node_type == "keyframe"

    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.execution_path_version == UNIFIED_PATH_VERSION
    assert op.status == "succeeded"
    assert op.provider_operation_id == "uni-img-1"
    assert op.resume_token is not None
    assert op.selection_plan is not None
    assert op.selection_plan["invoke_model_value"] == "uni-img-model"
    assert op.capability_manifest_hash is not None
    assert _current_runtime().submit_calls == 1


@pytest.mark.asyncio
async def test_director_unified_submission_uses_frozen_binding_not_project_reselection(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    project_binding = await session.scalar(
        select(ProjectProviderBinding).where(ProjectProviderBinding.project_id == run.project_id)
    )
    assert project_binding is not None
    frozen_binding_id = project_binding.model_binding_id
    await _attach_director_context(
        session,
        user=user,
        run=run,
        model_binding_id=frozen_binding_id,
    )

    # If execution tried to re-read the mutable project default, this invalid
    # UUID would fail selection. The immutable NodeRun snapshot must win.
    project_binding.model_binding_id = uuid4()
    await session.flush()

    result = await execute_media_node_run(session, node_run_id=run.id)

    assert result.node_type == "keyframe"
    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert op is not None
    assert op.model_binding_id == frozen_binding_id
    assert _current_runtime().submit_calls == 1


@pytest.mark.asyncio
async def test_director_keyframe_canonical_and_aspect_ratio_reach_compiled_request(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q1 contract: canonical lineage and portrait ratio survive Director -> Provider."""
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.purpose == "keyframe")
    )
    assert binding is not None
    batch = await _attach_director_context(
        session,
        user=user,
        run=run,
        model_binding_id=binding.id,
    )
    canonical = await _attach_canonical_source(
        session,
        user=user,
        run=run,
        batch=batch,
    )

    await execute_media_node_run(session, node_run_id=run.id)

    submitted = _current_runtime().submitted_image
    assert submitted is not None
    assert submitted.wire_request["size"] == "1080x1920"
    assert submitted.wire_request["reference_artifact_ids"] == [str(canonical.id)]
    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert op is not None
    compiled = op.request_summary["compiled_request"]
    assert isinstance(compiled, dict)
    assert compiled["size"] == "1080x1920"
    assert compiled["reference_artifact_ids"] == [str(canonical.id)]
    assert compiled["reference_fingerprints"] == [canonical.content_hash]
    assert op.request_summary["frozen_model_binding_id"] == str(binding.id)


@pytest.mark.asyncio
async def test_director_video_first_frame_ratio_duration_and_audio_reach_compiled_request(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q1 contract: a frozen Director shot reaches the provider without loss."""
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, workspace, keyframe_run = await _seed_project_chain(session)
    project_id = keyframe_run.project_id
    keyframe_node = await session.get(GraphNode, keyframe_run.graph_node_id)
    assert keyframe_node is not None
    video_node = GraphNode(
        graph_version_id=keyframe_run.graph_version_id,
        node_key="video",
        node_type="video",
        display_name="Video",
        cacheable=True,
    )
    session.add(video_node)
    await session.flush()
    session.add_all(
        [
            GraphEdge(
                graph_version_id=keyframe_run.graph_version_id,
                upstream_node_id=keyframe_node.id,
                output_port="image",
                downstream_node_id=video_node.id,
                input_port="first_frame",
                position=0,
                required=True,
            )
        ]
    )
    await session.flush()
    video_binding = await _seed_video_binding(
        session,
        workspace_id=workspace.id,
        project_id=project_id,
        user_id=user.id,
    )
    video_run = NodeRun(
        project_id=project_id,
        graph_version_id=keyframe_run.graph_version_id,
        graph_node_id=video_node.id,
        attempt_no=1,
        idempotency_key=f"director-video:{uuid4()}",
        input_hash="v" * 64,
        status="queued",
        input_snapshot={"plan": {"prompt": "director video"}},
        created_by=user.id,
    )
    session.add(video_run)
    await session.flush()
    batch = await _attach_director_context(
        session,
        user=user,
        run=video_run,
        model_binding_id=video_binding.id,
        purpose="video",
    )

    first_frame_bytes = b"approved-first-frame"
    stored = await get_object_store().put_bytes(
        object_key=f"projects/{project_id}/keyframes/{keyframe_run.id}.png",
        data=first_frame_bytes,
        mime_type="image/png",
    )
    first_frame = Artifact(
        project_id=project_id,
        artifact_type="image",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=keyframe_run.id,
    )
    session.add(first_frame)
    await session.flush()
    keyframe_run.production_batch_id = batch.id
    keyframe_run.status = "completed"
    keyframe_run.result_artifact_id = first_frame.id
    keyframe_run.input_snapshot = {"shot_id": "shot-1", "node_key": "keyframe"}
    video_run.input_snapshot = {
        **video_run.input_snapshot,
        "shot_id": "shot-1",
        "node_key": "video",
        "aspect_ratio": "16:9",
        "duration_seconds": "6",
    }
    await session.flush()

    await execute_media_node_run(session, node_run_id=video_run.id)

    submitted = _current_runtime().submitted_video
    assert submitted is not None
    assert submitted.wire_request["first_frame_artifact_id"] == str(first_frame.id)
    assert submitted.wire_request["aspect_ratio"] == "16:9"
    assert submitted.wire_request["duration_seconds"] == 6
    assert submitted.wire_request["generate_audio"] is False
    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == video_run.id)
    )
    assert op is not None
    compiled = op.request_summary["compiled_request"]
    assert isinstance(compiled, dict)
    assert compiled["reference_artifact_ids"] == [str(first_frame.id)]
    assert compiled["reference_fingerprints"] == [first_frame.content_hash]
    assert compiled["aspect_ratio"] == "16:9"
    assert compiled["duration_seconds"] == 6
    assert compiled["native_audio"] is False
    assert op.request_summary["frozen_model_binding_id"] == str(video_binding.id)


@pytest.mark.asyncio
async def test_director_unified_submission_without_budget_context_is_blocked_before_post(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    session.add(
        DirectorWorkflowRun(
            project_id=run.project_id,
            template_id="live_action_dialogue_short_v1",
            template_version="1.0.0",
            status="trial_running",
            current_stage="trial",
            current_artifact_versions={},
            created_by=user.id,
        )
    )
    await session.flush()

    with pytest.raises(DirectorExecutionGuardError) as caught:
        await execute_media_node_run(session, node_run_id=run.id)

    assert caught.value.code == "DIRECTOR_PRODUCTION_CONTEXT_REQUIRED"
    assert run.status == "blocked_budget"
    assert run.error_code == "DIRECTOR_PRODUCTION_CONTEXT_REQUIRED"
    assert (
        await session.scalar(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
        is None
    )


@pytest.mark.asyncio
async def test_unified_resume_never_recreates(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)
    connection_id = (
        await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == _workspace.id
            )
        )
    ).id
    run.status = "queued"
    op = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="keyframe.generate",
        actual_provider=FAKE_PROVIDER,
        actual_model="uni-img-model",
        protocol_profile=FAKE_PROFILE,
        request_fingerprint="f" * 64,
        status="running",
        request_summary={"kind": "keyframe"},
        response_summary={},
        submitted_at=None,
        provider_operation_id="uni-img-1",
        connection_id=connection_id,
        resume_token={
            "provider_type": FAKE_PROVIDER,
            "protocol_profile": FAKE_PROFILE,
            "remote_task_id": "uni-img-1",
            "query_kind": "task_id",
        },
        execution_path_version=UNIFIED_PATH_VERSION,
    )
    session.add(op)
    await session.flush()

    result = await execute_media_node_run(session, node_run_id=run.id)
    assert result.node_type == "keyframe"
    # Resume must never call submit again.
    assert _current_runtime().submit_calls == 0
    assert _current_runtime().poll_calls >= 1
    refreshed = await session.get(ProviderOperation, op.id)
    assert refreshed is not None and refreshed.status == "succeeded"


@pytest.mark.asyncio
async def test_submission_started_without_remote_id_is_unknown(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)
    run.status = "queued"
    op = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="keyframe.generate",
        actual_provider=FAKE_PROVIDER,
        actual_model="uni-img-model",
        protocol_profile=FAKE_PROFILE,
        request_fingerprint="f" * 64,
        status="submission_started",
        request_summary={"kind": "keyframe"},
        response_summary={},
        submitted_at=None,
        provider_operation_id=None,
        execution_path_version=UNIFIED_PATH_VERSION,
    )
    session.add(op)
    await session.flush()

    with pytest.raises(ValidationAppError) as exc_info:
        await execute_media_node_run(session, node_run_id=run.id)
    assert "PROVIDER_SUBMISSION_UNKNOWN" in str(exc_info.value)
    runtime = _FAKE_RUNTIME_HOLDER.get("runtime")
    assert runtime is None or runtime.submit_calls == 0
    refreshed = await session.get(ProviderOperation, op.id)
    assert refreshed is not None and refreshed.status == "unknown_submission"


@pytest.mark.asyncio
async def test_unbound_project_fails_closed_without_submit(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    # Seed everything EXCEPT the ProjectProviderBinding row.
    user = User(
        email=f"uni-{uuid4().hex}@example.com",
        display_name="Unified",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Uni-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name="Unified Unbound",
        aspect_ratio="9:16",
        actor=user,
    )
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="uni-test",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="Keyframe",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"uni:{uuid4()}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={
            "plan": {"prompt": "unbound"},
            "lead_identity_required": False,
        },
        created_by=user.id,
    )
    session.add(run)
    await session.flush()

    monkeypatch.setattr(
        "app.providers.registry.get_plugin",
        lambda *args: fake_plugin,  # type: ignore[arg-type]
    )
    with pytest.raises(ValidationAppError) as exc_info:
        await execute_media_node_run(session, node_run_id=run.id)
    assert exc_info.value.details["code"] == "MODEL_BINDING_MISSING"
    assert "runtime" not in _FAKE_RUNTIME_HOLDER


@pytest.mark.asyncio
async def test_unified_synchronous_image_skips_polling(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review gate 2: a synchronous image submission carries its result URL and
    must NOT poll the (fake image) remote task id."""
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)

    result = await execute_media_node_run(session, node_run_id=run.id)
    assert result.node_type == "keyframe"
    # Polling was skipped entirely for the synchronous image.
    assert _current_runtime().poll_calls == 0
    assert _current_runtime().submit_calls == 1
    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.status == "succeeded"
    assert op.provider_operation_id == "uni-img-1"


@pytest.mark.asyncio
async def test_unified_429_marks_rejected_and_retry_resubmits(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review gate 4: a 429 refusal is marked rejected (committed) and a retry
    resubmits the SAME op instead of escalating to unknown_submission."""
    from app.shared.errors import ProviderRateLimitedError

    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)

    _FAKE_IMAGE_PLAN.append("PROVIDER_RATE_LIMITED")
    with pytest.raises(ProviderRateLimitedError):
        await execute_media_node_run(session, node_run_id=run.id)

    op = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalar_one()
    assert op.status == "rejected"
    assert op.provider_operation_id is None

    # Scheduler requeues the run; the retry resubmits the same op (no duplicate).
    run.status = "queued"
    await session.flush()
    result = await execute_media_node_run(session, node_run_id=run.id)
    assert result.node_type == "keyframe"
    refreshed = await session.get(ProviderOperation, op.id)
    assert refreshed is not None
    assert refreshed.status == "succeeded"
    assert refreshed.provider_operation_id == "uni-img-1"
    # Exactly two submission attempts total (one refused, one accepted).
    assert _current_runtime().submit_calls == 1
    ops = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalars().all()
    assert len(ops) == 1
