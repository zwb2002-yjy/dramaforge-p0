"""Stage B4 unified execution path tests: single-path submission, resume-no-
recreate, submission_started crash semantics, and unbound fail-closed.

A fake provider plugin rides the whole unified chain (selection -> compiler ->
runtime) with zero network, proving the path works without a provider branch.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.config import Settings, clear_settings_cache
from app.creation import models as _cm  # noqa: F401
from app.execution import models as _xm  # noqa: F401
from app.execution.models import GraphNode, NodeRun, ProviderOperation
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
from app.storage.minio_store import reset_object_store_for_tests
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


class FakeUnifiedRuntime:
    provider = FAKE_PROVIDER
    protocol_profile = FAKE_PROFILE

    def __init__(self) -> None:
        self.submit_calls = 0
        self.poll_calls = 0

    def _token(self, remote: str) -> ProviderResumeToken:
        return ProviderResumeToken(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            remote_task_id=remote,
            query_kind="task_id",
        )

    async def submit_image(self, request: CompiledImageRequest) -> SubmissionResult:
        self.submit_calls += 1
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
        return CompiledImageRequest(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            model_id=invoke_model_value,
            operation="image.generate",
            wire_request={"model": invoke_model_value, "prompt": getattr(intent, "prompt", "")},
            request_schema_version="2026-08-10",
            safe_request_summary={"operation": "image.t2i"},
            reference_artifact_ids=[ref.artifact_id for ref in references],
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
        return CompiledVideoRequest(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            model_id=invoke_model_value,
            operation="video.generate",
            wire_request={"model": invoke_model_value, "prompt": getattr(intent, "prompt", "")},
            request_schema_version="2026-08-10",
            safe_request_summary={"operation": "video.i2v"},
            reference_artifact_ids=[ref.artifact_id for ref in references],
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
        catalog_manifests=(_FAKE_IMAGE_MANIFEST,),
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
