"""Stage B4 unified execution path tests: single-path submission, resume-no-
recreate, submission_started crash semantics, and unbound fail-closed.

A fake provider plugin rides the whole unified chain (selection -> compiler ->
runtime) with zero network, proving the path works without a provider branch.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.config import Settings, clear_settings_cache
from app.creation import models as _cm  # noqa: F401
from app.director.enums import ArtifactKind, WorkflowStatus
from app.director.execution_guard import DirectorExecutionGuardError
from app.director.models import (
    ApprovalRecord,
    BudgetAuthorization,
    BudgetReservation,
    CreativeArtifactVersion,
    DirectorWorkflowRun,
    ProductionBatch,
    ProductionBatchShot,
)
from app.director.production_service import DirectorProductionService
from app.events.models import OutboxEvent
from app.execution import models as _xm  # noqa: F401
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun, ProviderOperation
from app.execution.product_path import (
    UNIFIED_PATH_VERSION,
    execute_media_node_run,
)
from app.production import models as _pm  # noqa: F401
from app.production.execution_plan import WorkbenchExecutionPlan
from app.production.service import GraphService
from app.providers import registry as registry_module
from app.providers.capabilities import Capability
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.catalog_seed_data import hash_manifest
from app.providers.execution_identity import ExecutionIdentitySnapshot
from app.providers.model_profiles.orm import ProductionModelProfile
from app.providers.model_profiles.slots import ModelSlot
from app.providers.model_resolution import ExecutionModelResolution
from app.providers.models import (
    ProjectProviderBinding,
    ProviderConnection,
    ProviderConnectionRevision,
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
from app.runtime.scheduler import WorkerRuntime
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
_FAKE_IMAGE_PLAN: list[str | SubmissionResult] = []
_FAKE_COST_PLAN: list[CostResult] = []
_FAKE_IMAGE_SUBMISSION_NO = 0
_FAKE_VIDEO_SUBMISSION_NO = 0


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
                "aspect_ratio": "9:16",
                "duration_seconds": {"allowed": [5]},
                "num_frames": {"allowed": [121]},
                "frame_rate": {"allowed": [24]},
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
        self.factory_connection: object | None = None
        self.factory_settings: Settings | None = None

    def _token(self, remote: str) -> ProviderResumeToken:
        return ProviderResumeToken(
            provider_type=FAKE_PROVIDER,
            protocol_profile=FAKE_PROFILE,
            remote_task_id=remote,
            query_kind="task_id",
        )

    async def submit_image(self, request: CompiledImageRequest) -> SubmissionResult:
        global _FAKE_IMAGE_SUBMISSION_NO

        self.submit_calls += 1
        self.submitted_image = request
        if _FAKE_IMAGE_PLAN:
            outcome = _FAKE_IMAGE_PLAN.pop(0)
            if isinstance(outcome, SubmissionResult):
                return outcome
            code = outcome
            if code == "PROVIDER_RATE_LIMITED":
                return SubmissionResult(
                    status="failed",
                    error_code=code,
                    error="rate limited",
                    retry_after_seconds=5.0,
                    request_fingerprint="f" * 64,
                    request_summary={"operation": "image.t2i", "model": "uni-img-model"},
                )
        # A rejected submission creates no remote task.  Only successful
        # submissions consume a remote-id sequence number.
        _FAKE_IMAGE_SUBMISSION_NO += 1
        remote = f"uni-img-{_FAKE_IMAGE_SUBMISSION_NO}"
        return SubmissionResult(
            remote_task_id=remote,
            status="succeeded",
            artifact_uri="fake://image-result",
            request_fingerprint="f" * 64,
            request_summary={"operation": "image.t2i", "model": "uni-img-model"},
            resume_token=self._token(remote),
        )

    async def submit_video(self, request: CompiledVideoRequest) -> SubmissionResult:
        global _FAKE_VIDEO_SUBMISSION_NO

        self.submit_calls += 1
        self.submitted_video = request
        _FAKE_VIDEO_SUBMISSION_NO += 1
        remote = f"uni-vid-{_FAKE_VIDEO_SUBMISSION_NO}"
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
        if _FAKE_COST_PLAN:
            return _FAKE_COST_PLAN.pop(0)
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
        operation = model.operations["image.generate"]
        size = getattr(intent, "size", None) or operation.output_constraints["size"]
        aspect_ratio = (
            getattr(intent, "aspect_ratio", None)
            or operation.output_constraints["aspect_ratio"]
        )
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
                "size": size,
                "aspect_ratio": aspect_ratio,
                "reference_artifact_ids": reference_ids,
            },
            request_schema_version="2026-08-10",
            safe_request_summary={
                "operation": "image.i2i" if reference_ids else "image.t2i",
                "size": size,
                "aspect_ratio": aspect_ratio,
                "translation_transformations": (
                    [
                        {
                            "field": "size",
                            "from_value": None,
                            "to_value": size,
                            "reason": "frozen_manifest_native_size_tier",
                        }
                    ]
                    if getattr(intent, "size", None) is None
                    else []
                ),
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
        if aspect_ratio != "9:16" or duration_seconds != 5 or generate_audio is not False:
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
                "num_frames": 121,
                "frame_rate": 24,
                "generate_audio": generate_audio,
            },
            request_schema_version="2026-08-10",
            safe_request_summary={
                "operation": "video.i2v",
                "aspect_ratio": aspect_ratio,
                "duration_seconds": duration_seconds,
                "num_frames": 121,
                "frame_rate": 24,
                "native_audio": generate_audio,
                "reference_artifact_ids": [str(first_frame.artifact_id)],
                "reference_fingerprints": fingerprints,
            },
            reference_artifact_ids=[ref.artifact_id for ref in references],
            reference_fingerprints=fingerprints,
        )


_FAKE_RUNTIME_HOLDER: dict[str, FakeUnifiedRuntime] = {}
_FAKE_RUNTIMES: list[FakeUnifiedRuntime] = []


def _fake_plugin() -> ProviderPlugin:
    def _runtime_factory(**kwargs: object) -> FakeUnifiedRuntime:
        runtime = FakeUnifiedRuntime()
        runtime.factory_connection = kwargs.get("connection")
        raw_settings = kwargs.get("settings")
        runtime.factory_settings = raw_settings if isinstance(raw_settings, Settings) else None
        _FAKE_RUNTIME_HOLDER["runtime"] = runtime
        _FAKE_RUNTIMES.append(runtime)
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
    global _FAKE_IMAGE_SUBMISSION_NO, _FAKE_VIDEO_SUBMISSION_NO

    _FAKE_RUNTIME_HOLDER.clear()
    _FAKE_RUNTIMES.clear()
    _FAKE_IMAGE_PLAN.clear()
    _FAKE_COST_PLAN.clear()
    _FAKE_IMAGE_SUBMISSION_NO = 0
    _FAKE_VIDEO_SUBMISSION_NO = 0
    plugin = _fake_plugin()
    register_plugin(plugin)
    try:
        yield plugin
    finally:
        registry_module._registry.pop((FAKE_PROVIDER, FAKE_PROFILE), None)
        _FAKE_RUNTIME_HOLDER.clear()
        _FAKE_RUNTIMES.clear()
        _FAKE_IMAGE_PLAN.clear()
        _FAKE_COST_PLAN.clear()
        _FAKE_IMAGE_SUBMISSION_NO = 0
        _FAKE_VIDEO_SUBMISSION_NO = 0


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

    credential = await store_credential(
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
        credential_id=credential.id,
        credential_revision=credential.revision_no,
        enabled=True,
        verification_status="verified",
        created_by=user.id,
        updated_by=user.id,
    )
    session.add(connection)
    await session.flush()
    session.add(
        ProviderConnectionRevision(
            connection_id=connection.id,
            revision_no=1,
            provider_type=connection.provider_type,
            protocol_profile=connection.protocol_profile,
            base_url=connection.base_url,
            credential_revision_id=credential.id,
        )
    )
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
        pricing_snapshot_json={"unit_amount": "1", "currency": "USD"},
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
    currency: str = "USD",
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
        currency=currency,
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
        currency=currency,
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


async def _derive_repair_context(
    session: AsyncSession,
    *,
    user: User,
    run: NodeRun,
    root_batch: ProductionBatch,
    manifest_hash: str,
) -> tuple[ProductionBatch, BudgetAuthorization, BudgetReservation]:
    purpose = str((run.input_snapshot or {}).get("purpose") or "keyframe")
    frozen_binding_id = str((run.input_snapshot or {})["model_binding_id"])
    frozen_plan = {
        "purpose": purpose,
        "model_binding_id": frozen_binding_id,
        "manifest_hash": manifest_hash,
        "evidence": {
            "documented": True,
            "contract_tested": True,
            "account_verified": True,
            "quality_gated": False,
            "trial_only_until_quality_gated": True,
        },
    }
    root_batch.selection_snapshot = {"plans": [dict(frozen_plan)]}
    authorization = BudgetAuthorization(
        project_id=run.project_id,
        workflow_run_id=root_batch.workflow_run_id,
        authorization_kind="repair_budget",
        idempotency_key=f"repair-auth:{uuid4()}",
        pricing_snapshot_id="repair-pricing-v1",
        limit_amount=Decimal("10"),
        consumed_amount=Decimal("0"),
        currency="USD",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    repair = ProductionBatch(
        project_id=run.project_id,
        workflow_run_id=root_batch.workflow_run_id,
        batch_kind="repair",
        idempotency_key=f"repair-batch:{uuid4()}",
        status="running",
        budget_authorization_id=authorization.id,
        locked_version_refs={},
        selected_shot_ids=["shot-1"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={
            "plans": [dict(frozen_plan)],
            "source_batch_id": str(root_batch.id),
            "root_source_batch_id": str(root_batch.id),
        },
        semantic_hash="e" * 64,
        created_by=user.id,
    )
    session.add(repair)
    await session.flush()
    reservation = BudgetReservation(
        project_id=run.project_id,
        batch_id=repair.id,
        authorization_id=authorization.id,
        idempotency_key=f"repair-reservation:{uuid4()}",
        reserved_amount=Decimal("10"),
        currency="USD",
        status="reserved",
    )
    session.add(reservation)
    await session.flush()
    run.production_batch_id = repair.id
    run.budget_reservation_id = reservation.id
    run.input_snapshot = {
        **(run.input_snapshot or {}),
        "production_batch_id": str(repair.id),
        "budget_reservation_id": str(reservation.id),
        "selection_plan": dict(frozen_plan),
    }
    await session.flush()
    return repair, authorization, reservation


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
        # ``_seed_project_chain`` already owns attempt 1 for this graph node;
        # the canonical source is the next valid attempt.
        attempt_no=2,
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
        pricing_snapshot_json={"unit_amount": "1", "currency": "USD"},
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
async def test_director_trial_materialization_reaches_unified_artifacts_once(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G2 smoke: real Director authorization -> graph/outbox -> Worker -> Artifact."""
    _byok(monkeypatch)
    monkeypatch.setattr(
        "app.execution.product_path.get_settings",
        lambda: Settings(provider_unified_path_enabled=False, source_commit="g2-spy"),
    )
    monkeypatch.setattr(
        "app.director.production_service.get_settings",
        lambda: Settings(provider_unified_path_enabled=False, source_commit="g2-spy"),
    )
    await _no_sleep(monkeypatch)
    user, workspace, seed_run = await _seed_project_chain(session)
    project = await session.get(Project, seed_run.project_id)
    assert project is not None
    image_binding = await session.scalar(
        select(ProviderModelBinding).where(
            ProviderModelBinding.workspace_id == workspace.id,
            ProviderModelBinding.purpose == "keyframe",
        )
    )
    assert image_binding is not None and image_binding.catalog_entry_id is not None
    image_binding.quality_gated = False
    image_entry = await session.get(ModelCatalogEntry, image_binding.catalog_entry_id)
    assert image_entry is not None
    video_binding = await _seed_video_binding(
        session,
        workspace_id=workspace.id,
        project_id=project.id,
        user_id=user.id,
    )
    assert video_binding.catalog_entry_id is not None
    video_entry = await session.get(ModelCatalogEntry, video_binding.catalog_entry_id)
    assert video_entry is not None

    workflow = DirectorWorkflowRun(
        project_id=project.id,
        template_id="live_action_dialogue_short_v1",
        template_version="1.0.0",
        status=WorkflowStatus.TRIAL_RUNNING.value,
        current_stage="trial",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()

    def selection_plan(
        purpose: str,
        *,
        binding: ProviderModelBinding | None,
        entry: ModelCatalogEntry | None,
        unit_amount: str,
    ) -> dict[str, object]:
        is_video = purpose == "video"
        return {
            "purpose": purpose,
            "model_binding_id": str(binding.id) if binding is not None else None,
            "provider_type": FAKE_PROVIDER if binding is not None else "local_tts",
            "protocol_profile": FAKE_PROFILE if binding is not None else "local-v1",
            "model_id": (
                "uni-vid-model" if is_video else "uni-img-model"
            ) if binding is not None else "local-tts-v1",
            "invoke_model_value": binding.invoke_model_value if binding is not None else None,
            "manifest_hash": entry.contract_manifest_hash if entry is not None else None,
            "required_capabilities": (
                ["video.i2v.first_frame"]
                if is_video
                else ["image.i2i"]
                if purpose == "keyframe"
                else ["image.t2i"]
                if purpose == "character_reference"
                else []
            ),
            "supported_capabilities": (
                ["video.i2v.first_frame"]
                if is_video
                else ["image.t2i", "image.i2i"]
                if binding is not None
                else []
            ),
            "evidence": {
                "documented": True,
                "contract_tested": True,
                "account_verified": True,
                "quality_gated": binding.quality_gated if binding is not None else True,
                "trial_only_until_quality_gated": bool(
                    binding is not None and not binding.quality_gated
                ),
            },
            "pricing_snapshot": {"unit_amount": unit_amount, "currency": "USD"},
            "status": "ready",
            "blockers": [],
        }

    plans = [
        selection_plan(
            "character_reference",
            binding=image_binding,
            entry=image_entry,
            unit_amount="1",
        ),
        selection_plan(
            "keyframe",
            binding=image_binding,
            entry=image_entry,
            unit_amount="1",
        ),
        selection_plan(
            "video",
            binding=video_binding,
            entry=video_entry,
            unit_amount="1",
        ),
        selection_plan("voice", binding=None, entry=None, unit_amount="0"),
    ]
    known_line = {
        "quantity": 1,
        "unit_amount": "1",
        "estimated_amount": "1",
        "currency": "USD",
        "status": "known",
    }
    storyboard = {
        "template_key": "live_action_dialogue_short_v1",
        "aspect_ratio": "9:16",
        "target_duration_seconds": 15,
        "shots": [
            {
                "shot_id": f"shot-{number}",
                "shot_number": number,
                "duration_seconds": "5",
                "location": "fictional studio",
                "time_of_day": "night",
                "shot_type": "medium_close",
                "camera_move": "static",
                "characters": ["Lin"],
                "action": f"Lin completes fictional beat {number}",
                "dialogue": [
                    {
                        "speaker": "Lin",
                        "text": f"fictional line {number}",
                        "emotion": "restrained",
                    }
                ],
                "image_prompt": f"portrait keyframe {number}",
                "video_prompt": f"subtle performance {number}",
                "transition": "cut",
            }
            for number in range(1, 4)
        ],
    }
    payloads: dict[ArtifactKind, dict[str, object]] = {
        ArtifactKind.CHARACTER_BIBLE: {
            "policy": "fictional_characters_only",
            "real_person_reference_allowed": False,
            "characters": [
                {
                    "character_id": "lin",
                    "name": "Lin",
                    "age_range": "25-30",
                    "facial_features": "oval face and dark eyes",
                    "hair": "short black hair",
                    "body_shape": "slender",
                    "wardrobe": "black fictional coat",
                    "distinguishing_features": ["small fictional mole"],
                    "locked_prompt": "fictional adult woman with an oval face",
                    "negative_prompt": "real person",
                }
            ],
        },
        ArtifactKind.VISUAL_BIBLE: {
            "medium": "photorealistic_live_action",
            "aspect_ratio": "9:16",
            "era_and_setting": "contemporary fictional studio",
            "color_palette": "cool blue with neutral skin tones",
            "lighting": "soft practical light",
            "lens_language": "restrained medium close shots",
            "continuity_rules": ["preserve hair and coat"],
            "preview_is_generated_media": False,
        },
        ArtifactKind.VOICE_BIBLE: {
            "language": "zh-CN",
            "voice_clone_allowed": False,
            "voices": [
                {
                    "character_id": "lin",
                    "character_name": "Lin",
                    "voice_description": "calm licensed fictional voice",
                    "pace": "medium",
                    "emotional_range": ["restrained"],
                    "voice_clone": False,
                }
            ],
        },
        ArtifactKind.STORYBOARD_PLAN: storyboard,
        ArtifactKind.RISK_REPORT: {
            "status": "ready",
            "representative_shot_id": "shot-1",
            "representative_shot_reason": "identity and dialogue evidence",
            "risks": [],
        },
        ArtifactKind.SELECTION_PLAN: {
            "status": "ready",
            "plans": plans,
            "fallback_allowed": False,
            "advanced_parameters_hidden_in_quick_mode": True,
        },
        ArtifactKind.COST_ESTIMATE: {
            "pricing_snapshot_id": "g2-spy-price-v1",
            "currency": "USD",
            "trial": [
                {**known_line, "purpose": purpose}
                for purpose in ("character_reference", "keyframe", "video")
            ]
            + [
                {
                    **known_line,
                    "purpose": "voice",
                    "unit_amount": "0",
                    "estimated_amount": "0",
                }
            ],
            "production": [
                {
                    **known_line,
                    "purpose": purpose,
                    "quantity": 3,
                    "estimated_amount": "3",
                }
                for purpose in ("keyframe", "video")
            ]
            + [
                {
                    **known_line,
                    "purpose": "voice",
                    "quantity": 3,
                    "unit_amount": "0",
                    "estimated_amount": "0",
                }
            ],
            "repair": [{**known_line, "purpose": "video"}],
            "trial_total": "3",
            "production_total": "6",
            "repair_total": "1",
            "requires_user_budget_limit": True,
            "disclaimer": "Frozen fake prices; no external request is made.",
        },
        ArtifactKind.TRIAL_PLAN: {
            "representative_shot_id": "shot-1",
            "selection_reason": "identity and dialogue evidence",
            "planned_operations": ["character_reference", "keyframe", "video", "voice"],
            "quality_dimensions": ["request_contract", "identity", "continuity"],
            "budget_authorization_required": True,
        },
    }
    locked_refs: dict[str, str] = {}
    for kind, payload in payloads.items():
        artifact_version = CreativeArtifactVersion(
            project_id=project.id,
            workflow_run_id=workflow.id,
            artifact_kind=kind.value,
            revision_no=1,
            source_kind="user",
            payload=payload,
            content_hash=hashlib.sha256(f"g2:{kind.value}".encode()).hexdigest(),
            status="locked",
            locked_at=datetime.now(UTC),
            created_by=user.id,
        )
        session.add(artifact_version)
        await session.flush()
        locked_refs[kind.value] = str(artifact_version.id)
    workflow.current_artifact_versions = dict(locked_refs)
    authorization = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind="trial_budget",
        idempotency_key="g2-spy-trial-budget",
        pricing_snapshot_id="g2-spy-price-v1",
        limit_amount=Decimal("10"),
        consumed_amount=Decimal("0"),
        currency="USD",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    session.add(
        ApprovalRecord(
            project_id=project.id,
            workflow_run_id=workflow.id,
            approval_kind="trial_budget",
            idempotency_key="g2-spy-trial-approval",
            approved_artifact_versions=locked_refs,
            budget_authorization_id=authorization.id,
            reason="Explicit zero-network G2 authorization fixture",
            approved_by=user.id,
        )
    )
    await session.flush()

    batch, runs = await DirectorProductionService(session).materialize_trial(
        project_id=project.id,
        actor=user,
        idempotency_key="g2-spy-materialize-trial",
    )

    assert batch.status == "running"
    assert batch.batch_kind == "trial"
    assert batch.selection_snapshot["fallback_allowed"] is False
    batch_shot = await session.scalar(
        select(ProductionBatchShot).where(ProductionBatchShot.batch_id == batch.id)
    )
    assert batch_shot is not None and batch_shot.graph_version_id is not None
    graph_version = await session.get(_pm.GraphVersion, batch_shot.graph_version_id)
    assert graph_version is not None and graph_version.status == "published"
    graph = await session.get(_pm.ProductionGraph, graph_version.graph_id)
    assert graph is not None and graph.project_id == project.id

    run_rows = list(
        (
            await session.execute(
                select(NodeRun, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(NodeRun.production_batch_id == batch.id)
            )
        ).tuples()
    )
    by_key = {node.node_key: run for run, node in run_rows}
    assert set(by_key) == {
        "character_lin",
        "prompt",
        "keyframe",
        "identity_review",
        "video",
        "video_drift_review",
        "voice",
        "subtitle",
        "composite",
        "continuity_review",
    }
    assert {run.id for run in runs} == {run.id for run, _node in run_rows}
    assert all(run.status == "queued" for run in runs)
    assert all(run.input_snapshot["source_commit"] == "g2-spy" for run in runs)
    outbox = list(
        (
            await session.execute(
                select(OutboxEvent).where(
                    OutboxEvent.project_id == project.id,
                    OutboxEvent.topic == "node_run.enqueue",
                )
            )
        ).scalars()
    )
    assert {str(event.payload["node_run_id"]) for event in outbox} == {
        str(run.id) for run in runs
    }
    edges = list(
        (
            await session.execute(
                select(GraphEdge).where(
                    GraphEdge.graph_version_id == batch_shot.graph_version_id
                )
            )
        ).scalars()
    )
    node_keys = {node.id: node.node_key for _run, node in run_rows}
    edge_keys = {
        (node_keys[edge.upstream_node_id], node_keys[edge.downstream_node_id])
        for edge in edges
    }
    assert {
        ("character_lin", "keyframe"),
        ("prompt", "keyframe"),
        ("keyframe", "video"),
    }.issubset(edge_keys)

    worker = WorkerRuntime(session)
    execution_order = ["character_lin", "prompt", "keyframe", "video"]
    for key in execution_order:
        assert await worker.process_one(by_key[key].id) is True
        await session.refresh(by_key[key])
        assert by_key[key].status == "completed"
        assert by_key[key].result_artifact_id is not None

    submit_count = sum(runtime.submit_calls for runtime in _FAKE_RUNTIMES)
    assert submit_count == 3
    for key in execution_order:
        assert await worker.process_one(by_key[key].id) is True
    assert sum(runtime.submit_calls for runtime in _FAKE_RUNTIMES) == submit_count

    operations = list(
        (
            await session.execute(
                select(ProviderOperation).where(
                    ProviderOperation.node_run_id.in_(
                        [by_key[key].id for key in execution_order]
                    )
                )
            )
        ).scalars()
    )
    op_by_key = {
        next(key for key, run in by_key.items() if run.id == operation.node_run_id): operation
        for operation in operations
    }
    assert set(op_by_key) == {"character_lin", "keyframe", "video"}
    for key, operation in op_by_key.items():
        expected_binding = video_binding if key == "video" else image_binding
        expected_entry = video_entry if key == "video" else image_entry
        assert operation.execution_path_version == UNIFIED_PATH_VERSION
        assert operation.status == "succeeded"
        assert operation.model_binding_id == expected_binding.id
        assert operation.catalog_entry_id == expected_entry.id
        assert operation.capability_manifest_hash == expected_entry.contract_manifest_hash
        expected_revision = await session.scalar(
            select(ProviderConnectionRevision)
            .where(ProviderConnectionRevision.connection_id == operation.connection_id)
            .order_by(ProviderConnectionRevision.revision_no.desc())
            .limit(1)
        )
        assert expected_revision is not None
        assert operation.provider_connection_revision_id == expected_revision.id
        assert operation.selection_plan is not None
        assert operation.resume_token is not None
        assert operation.request_summary["frozen_model_binding_id"] == str(
            expected_binding.id
        )
        assert operation.request_summary["capability_manifest_hash"] == (
            expected_entry.contract_manifest_hash
        )
        assert operation.request_summary["translation_report"]["dropped_options"] == []

    character_artifact = await session.get(Artifact, by_key["character_lin"].result_artifact_id)
    keyframe_artifact = await session.get(Artifact, by_key["keyframe"].result_artifact_id)
    video_artifact = await session.get(Artifact, by_key["video"].result_artifact_id)
    assert character_artifact is not None
    assert keyframe_artifact is not None
    assert video_artifact is not None
    assert character_artifact.produced_by_run_id == by_key["character_lin"].id
    assert keyframe_artifact.produced_by_run_id == by_key["keyframe"].id
    assert video_artifact.produced_by_run_id == by_key["video"].id

    character_effective = op_by_key["character_lin"].request_summary["effective_request"]
    keyframe_effective = op_by_key["keyframe"].request_summary["effective_request"]
    video_effective = op_by_key["video"].request_summary["effective_request"]
    assert character_effective["reference_artifact_ids"] == []
    assert keyframe_effective["reference_artifact_ids"] == [str(character_artifact.id)]
    assert keyframe_effective["reference_fingerprints"] == [
        character_artifact.content_hash
    ]
    assert keyframe_effective["common_options"] == {
        "size": "1K",
        "aspect_ratio": "9:16",
    }
    assert op_by_key["keyframe"].request_summary["translation_report"][
        "transformations"
    ] == [
        {
            "field": "size",
            "from_value": None,
            "to_value": "1K",
            "reason": "frozen_manifest_native_size_tier",
        }
    ]
    assert video_effective["reference_artifact_ids"] == [str(keyframe_artifact.id)]
    assert video_effective["reference_fingerprints"] == [keyframe_artifact.content_hash]
    assert video_effective["common_options"] == {
        "aspect_ratio": "9:16",
        "duration_seconds": 5,
        "frame_rate": 24,
        "num_frames": 121,
        "generate_audio": False,
    }
    assert op_by_key["video"].provider_operation_id == "uni-vid-1"
    assert op_by_key["video"].resume_token["remote_task_id"] == "uni-vid-1"
    reservation = await session.get(BudgetReservation, by_key["video"].budget_reservation_id)
    refreshed_authorization = await session.get(BudgetAuthorization, authorization.id)
    assert reservation is not None and reservation.actual_amount == Decimal("3.75")
    assert refreshed_authorization is not None
    assert refreshed_authorization.consumed_amount == Decimal("3.75")


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
    await session.refresh(run)
    resolution_snapshot = (run.input_snapshot or {}).get("execution_model_resolution")
    assert isinstance(resolution_snapshot, dict)
    assert resolution_snapshot["status"] == "RESOLVED"
    assert resolution_snapshot["mode_id"] == "text_to_image"
    assert resolution_snapshot["provider_model_binding_id"] == str(op.model_binding_id)
    assert op.request_summary["execution_model_resolution"] == resolution_snapshot
    identity_snapshot = (run.input_snapshot or {}).get("execution_identity")
    assert isinstance(identity_snapshot, dict)
    assert op.selection_plan["execution_identity"] == identity_snapshot
    assert op.request_summary["execution_identity"] == identity_snapshot
    assert identity_snapshot["provider_connection_revision_id"] == str(
        op.provider_connection_revision_id
    )
    frozen_revision = await session.get(
        ProviderConnectionRevision, op.provider_connection_revision_id
    )
    assert frozen_revision is not None
    assert identity_snapshot["credential_revision_id"] == str(
        frozen_revision.credential_revision_id
    )
    # The runtime that reaches the Provider boundary is rebuilt from the
    # immutable connection revision, rather than retaining the mutable
    # ProviderConnection object used during selection.
    assert (
        type(_current_runtime().factory_connection).__name__
        == "FrozenProviderConnection"
    )
    assert _current_runtime().factory_connection.base_url == frozen_revision.base_url
    assert _current_runtime().factory_settings.unified_test_api_key == "uni-secret"
    assert _current_runtime().submit_calls == 1


@pytest.mark.asyncio
async def test_professional_workbench_node_uses_frozen_unified_provider_path(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queued P4 Workbench NodeRun must never fall through to Flux/Kling.

    The test keeps the feature flag off and makes both legacy adapter factories
    fail if touched.  The persisted Workbench plan is the only model decision;
    the fake Provider runtime proves the request still completes through the
    registry/resolver/compiler chain.
    """
    _byok(monkeypatch)
    monkeypatch.setattr(
        "app.execution.product_path.get_settings",
        lambda: Settings(provider_unified_path_enabled=False),
    )
    await _no_sleep(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.purpose == "keyframe")
    )
    assert binding is not None
    connection = await session.get(ProviderConnection, binding.connection_id)
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    assert connection is not None and entry is not None
    revision = await session.scalar(
        select(ProviderConnectionRevision).where(
            ProviderConnectionRevision.connection_id == connection.id
        )
    )
    assert revision is not None
    resolution = ExecutionModelResolution(
        requested_model=f"{FAKE_PROVIDER}/{binding.model_id}",
        resolved_model_id=f"{FAKE_PROVIDER}/{binding.model_id}",
        source="request_override",
        status="RESOLVED",
        provider_model_binding_id=binding.id,
        provider_connection_id=connection.id,
        provider_connection_revision_id=revision.id,
        credential_revision_id=revision.credential_revision_id,
        catalog_entry_id=entry.id,
        model_revision=entry.model_revision,
        manifest_hash=entry.contract_manifest_hash,
        invoke_model_value=binding.invoke_model_value,
        capability=Capability.IMAGE_GENERATE,
        mode_id="text_to_image",
    )
    workbench_plan = WorkbenchExecutionPlan(
        project_id=run.project_id,
        shot_id=run.project_id,
        stage="image_keyframe",
        prompt="workbench frozen keyframe",
        mode_id="text_to_image",
        resolved_model=resolution,
        capability=Capability.IMAGE_GENERATE,
        connection_revision_id=revision.id,
        credential_revision_id=revision.credential_revision_id,
    ).freeze()
    resolution_json = resolution.model_dump(mode="json")
    run.input_snapshot = {
        **run.input_snapshot,
        "professional_unified": True,
        "workbench_plan": workbench_plan.model_dump(mode="json"),
        "model_binding_id": str(binding.id),
        "execution_model_resolution": resolution_json,
        "selection_plan": {
            "purpose": "keyframe",
            "mode": "text_to_image",
            "mode_id": "text_to_image",
            "model_binding_id": str(binding.id),
            "provider_type": FAKE_PROVIDER,
            "protocol_profile": FAKE_PROFILE,
            "catalog_entry_id": str(entry.id),
            "model_id": f"{FAKE_PROVIDER}/{binding.model_id}",
            "invoke_model_value": binding.invoke_model_value,
            "connection_id": str(connection.id),
            "manifest_hash": entry.contract_manifest_hash,
            "execution_model_resolution": resolution_json,
            "evidence": {"professional_unified": True},
        },
    }
    await session.flush()

    import app.providers.flux as flux_module
    import app.providers.kling as kling_module

    async def legacy_factory_must_not_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("Professional Workbench touched a legacy adapter")

    monkeypatch.setattr(
        flux_module,
        "get_flux_adapter_for_workspace",
        legacy_factory_must_not_run,
    )
    monkeypatch.setattr(
        kling_module,
        "get_kling_adapter_for_workspace",
        legacy_factory_must_not_run,
    )

    result = await execute_media_node_run(session, node_run_id=run.id)

    assert result.node_type == "keyframe"
    operation = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert operation is not None
    assert operation.execution_path_version == UNIFIED_PATH_VERSION
    assert operation.actual_provider == FAKE_PROVIDER
    assert operation.actual_provider not in {"flux", "kling"}
    assert _current_runtime().submit_calls == 1
    assert type(_current_runtime().factory_connection).__name__ == "FrozenProviderConnection"


@pytest.mark.asyncio
async def test_unavailable_profile_model_stops_before_provider_submission(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared Profile model X may not fall through to legacy binding Y."""
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, workspace, run = await _seed_project_chain(session)
    session.add(
        ProductionModelProfile(
            workspace_id=workspace.id,
            project_id=None,
            name="Missing keyframe model",
            version=1,
            is_default=True,
            bindings={
                ModelSlot.VISUAL_KEYFRAME.value: {
                    "slot": ModelSlot.VISUAL_KEYFRAME.value,
                    "model_id": f"{FAKE_PROVIDER}/missing-image-model",
                    "native_options": {},
                    "enabled": True,
                }
            },
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await session.flush()

    with pytest.raises(ValidationAppError) as exc_info:
        await execute_media_node_run(session, node_run_id=run.id)

    assert exc_info.value.details["code"] == "MODEL_BINDING_UNAVAILABLE"
    assert exc_info.value.details["source"] == "workspace_profile"
    assert _FAKE_RUNTIME_HOLDER.get("runtime") is None
    assert await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    ) is None


@pytest.mark.asyncio
async def test_unified_create_failure_persists_structured_provider_evidence(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)
    _FAKE_IMAGE_PLAN.append(
        SubmissionResult(
            status="failed",
            error_code="PROVIDER_UNAVAILABLE",
            error="provider unavailable",
            http_status=503,
            retry_after_seconds=17.0,
        )
    )

    with pytest.raises(
        ValidationAppError,
        match="PROVIDER_CREATE_FAILED: provider unavailable",
    ):
        await execute_media_node_run(session, node_run_id=run.id)

    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert op is not None
    assert op.error_code == "PROVIDER_CREATE_FAILED"
    assert op.response_summary == {
        "create_status": "failed",
        "create_error": "provider unavailable",
        "provider_error_code": "PROVIDER_UNAVAILABLE",
        "create_http_status": 503,
        "retry_after_seconds": 17.0,
    }


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
async def test_director_forces_unified_path_when_feature_flag_is_false(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    monkeypatch.setattr(
        "app.execution.product_path.get_settings",
        lambda: Settings(provider_unified_path_enabled=False),
    )
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.purpose == "keyframe")
    )
    assert binding is not None
    await _attach_director_context(
        session,
        user=user,
        run=run,
        model_binding_id=binding.id,
    )

    await execute_media_node_run(session, node_run_id=run.id)

    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert op is not None
    assert op.execution_path_version == UNIFIED_PATH_VERSION
    assert _current_runtime().submit_calls == 1


@pytest.mark.asyncio
async def test_trial_derived_repair_can_bootstrap_quality_gate(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.purpose == "keyframe")
    )
    assert binding is not None and binding.catalog_entry_id is not None
    binding.quality_gated = False
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    assert entry is not None
    root = await _attach_director_context(
        session,
        user=user,
        run=run,
        model_binding_id=binding.id,
    )
    await _derive_repair_context(
        session,
        user=user,
        run=run,
        root_batch=root,
        manifest_hash=entry.contract_manifest_hash,
    )

    await execute_media_node_run(session, node_run_id=run.id)

    operation = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert operation is not None
    assert operation.model_binding_id == binding.id
    assert operation.capability_manifest_hash == entry.contract_manifest_hash
    assert operation.selection_plan["evidence"]["trial_quality_gate_exception"] is True
    assert _current_runtime().submit_calls == 1


@pytest.mark.asyncio
async def test_production_derived_repair_cannot_bootstrap_quality_gate(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.purpose == "keyframe")
    )
    assert binding is not None and binding.catalog_entry_id is not None
    binding.quality_gated = False
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    assert entry is not None
    root = await _attach_director_context(
        session,
        user=user,
        run=run,
        model_binding_id=binding.id,
    )
    root.batch_kind = "production"
    root_authorization = await session.get(
        BudgetAuthorization, root.budget_authorization_id
    )
    assert root_authorization is not None
    root_authorization.authorization_kind = "production_budget"
    _repair, authorization, reservation = await _derive_repair_context(
        session,
        user=user,
        run=run,
        root_batch=root,
        manifest_hash=entry.contract_manifest_hash,
    )

    with pytest.raises(ValidationAppError) as caught:
        await execute_media_node_run(session, node_run_id=run.id)

    assert caught.value.details["code"] == "MODEL_INELIGIBLE"
    assert caught.value.details["issues"] == ["MODEL_QUALITY_GATE_MISSING"]
    assert (
        await session.scalar(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
        is None
    )
    await session.refresh(authorization)
    await session.refresh(reservation)
    assert authorization.consumed_amount == Decimal("0")
    assert reservation.actual_amount is None
    assert "runtime" not in _FAKE_RUNTIME_HOLDER


@pytest.mark.parametrize("drift_field", ["model_binding_id", "manifest_hash"])
@pytest.mark.asyncio
async def test_trial_repair_rejects_frozen_model_snapshot_drift_before_submit(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
    drift_field: str,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.purpose == "keyframe")
    )
    assert binding is not None and binding.catalog_entry_id is not None
    binding.quality_gated = False
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    assert entry is not None
    root = await _attach_director_context(
        session,
        user=user,
        run=run,
        model_binding_id=binding.id,
    )
    repair, authorization, reservation = await _derive_repair_context(
        session,
        user=user,
        run=run,
        root_batch=root,
        manifest_hash=entry.contract_manifest_hash,
    )
    drift_value = str(uuid4()) if drift_field == "model_binding_id" else "f" * 64
    repair_plan = dict(repair.selection_snapshot["plans"][0])
    repair_plan[drift_field] = drift_value
    repair.selection_snapshot = {
        **repair.selection_snapshot,
        "plans": [repair_plan],
    }
    node_plan = dict(run.input_snapshot["selection_plan"])
    node_plan[drift_field] = drift_value
    run.input_snapshot = {
        **run.input_snapshot,
        "model_binding_id": (
            drift_value
            if drift_field == "model_binding_id"
            else run.input_snapshot["model_binding_id"]
        ),
        "selection_plan": node_plan,
    }
    await session.flush()

    with pytest.raises(DirectorExecutionGuardError) as caught:
        await execute_media_node_run(session, node_run_id=run.id)

    assert caught.value.code == "DIRECTOR_REPAIR_MODEL_SNAPSHOT_MISMATCH"
    assert (
        await session.scalar(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
        is None
    )
    await session.refresh(authorization)
    await session.refresh(reservation)
    assert authorization.consumed_amount == Decimal("0")
    assert reservation.actual_amount is None
    assert "runtime" not in _FAKE_RUNTIME_HOLDER


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
    assert submitted.wire_request["size"] == "1K"
    assert submitted.wire_request["aspect_ratio"] == "9:16"
    assert submitted.wire_request["reference_artifact_ids"] == [str(canonical.id)]
    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert op is not None
    compiled = op.request_summary["compiled_request"]
    assert isinstance(compiled, dict)
    assert compiled["size"] == "1K"
    assert compiled["aspect_ratio"] == "9:16"
    assert compiled["reference_artifact_ids"] == [str(canonical.id)]
    assert compiled["reference_fingerprints"] == [canonical.content_hash]
    assert op.request_summary["frozen_model_binding_id"] == str(binding.id)
    effective = op.request_summary["effective_request"]
    assert isinstance(effective, dict)
    assert effective["reference_artifact_ids"] == [str(canonical.id)]
    assert effective["reference_fingerprints"] == [canonical.content_hash]
    translation = op.request_summary["translation_report"]
    assert isinstance(translation, dict)
    assert translation["dropped_options"] == []
    assert translation["transformations"] == [
        {
            "field": "size",
            "from_value": None,
            "to_value": "1K",
            "reason": "frozen_manifest_native_size_tier",
        }
    ]


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
        "aspect_ratio": "9:16",
        "duration_seconds": "5",
    }
    await session.flush()

    await execute_media_node_run(session, node_run_id=video_run.id)

    submitted = _current_runtime().submitted_video
    assert submitted is not None
    assert submitted.wire_request["first_frame_artifact_id"] == str(first_frame.id)
    assert submitted.wire_request["aspect_ratio"] == "9:16"
    assert submitted.wire_request["duration_seconds"] == 5
    assert submitted.wire_request["generate_audio"] is False
    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == video_run.id)
    )
    assert op is not None
    compiled = op.request_summary["compiled_request"]
    assert isinstance(compiled, dict)
    assert compiled["reference_artifact_ids"] == [str(first_frame.id)]
    assert compiled["reference_fingerprints"] == [first_frame.content_hash]
    assert compiled["aspect_ratio"] == "9:16"
    assert compiled["duration_seconds"] == 5
    assert compiled["native_audio"] is False
    assert op.request_summary["frozen_model_binding_id"] == str(video_binding.id)
    effective = op.request_summary["effective_request"]
    assert isinstance(effective, dict)
    assert effective["common_options"] == {
        "aspect_ratio": "9:16",
        "duration_seconds": 5,
        "frame_rate": 24,
        "num_frames": 121,
        "generate_audio": False,
    }
    assert effective["reference_artifact_ids"] == [str(first_frame.id)]
    assert effective["reference_fingerprints"] == [first_frame.content_hash]
    translation = op.request_summary["translation_report"]
    assert isinstance(translation, dict)
    assert translation["dropped_options"] == []


@pytest.mark.asyncio
async def test_unified_unreported_cost_remains_null_and_unsettled(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    binding = await session.scalar(
        select(ProviderModelBinding).where(ProviderModelBinding.purpose == "keyframe")
    )
    assert binding is not None
    binding.pricing_snapshot_json = {"unit_amount": "0", "currency": "CNY"}
    batch = await _attach_director_context(
        session,
        user=user,
        run=run,
        model_binding_id=binding.id,
        currency="CNY",
    )
    _FAKE_COST_PLAN.append(
        CostResult(amount=None, currency="USD", units=1.0, cost_status="not_reported")
    )

    await execute_media_node_run(session, node_run_id=run.id)

    op = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
    )
    assert op is not None
    assert op.provider_cost is None
    assert op.currency == "CNY"
    assert op.response_summary["cost_status"] == "not_reported"
    assert op.response_summary["provider_reported_cost"] is None
    assert op.response_summary["director_budget_settled"] is False
    reservation = await session.get(BudgetReservation, run.budget_reservation_id)
    authorization = await session.get(BudgetAuthorization, batch.budget_authorization_id)
    assert reservation is not None and reservation.actual_amount is None
    assert authorization is not None and authorization.consumed_amount == Decimal("0")


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
@pytest.mark.asyncio
async def test_unified_frozen_identity_mismatch_fails_before_provider_call(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)
    run.status = "queued"
    run.input_snapshot = {"execution_identity": {"malformed": True}}
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
        request_summary={},
        response_summary={},
        provider_operation_id="uni-img-1",
        selection_plan={"execution_identity": {"malformed": True}},
        execution_path_version=UNIFIED_PATH_VERSION,
    )
    session.add(op)
    await session.flush()

    with pytest.raises(ValidationAppError) as caught:
        await execute_media_node_run(session, node_run_id=run.id)
    assert caught.value.details["code"] == "EXECUTION_IDENTITY_INVALID"
    assert _FAKE_RUNTIME_HOLDER == {}


@pytest.mark.asyncio
async def test_unified_resume_never_recreates(
    session: AsyncSession,
    fake_plugin: ProviderPlugin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _byok(monkeypatch)
    _enable_unified(monkeypatch)
    await _no_sleep(monkeypatch)
    user, _workspace, run = await _seed_project_chain(session)
    connection = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == _workspace.id
        )
    )
    assert connection is not None
    connection_id = connection.id
    original_revision = await session.scalar(
        select(ProviderConnectionRevision)
        .where(ProviderConnectionRevision.connection_id == connection.id)
        .order_by(ProviderConnectionRevision.revision_no.desc())
        .limit(1)
    )
    assert original_revision is not None
    binding = await session.scalar(
        select(ProviderModelBinding).where(
            ProviderModelBinding.connection_id == connection.id,
            ProviderModelBinding.purpose == "keyframe",
        )
    )
    assert binding is not None and binding.catalog_entry_id is not None
    entry = await session.get(ModelCatalogEntry, binding.catalog_entry_id)
    assert entry is not None
    identity = ExecutionIdentitySnapshot(
        requested_model="uni-img-model",
        resolved_model="uni-img-model",
        resolution_source="request_override",
        provider_model_binding_id=binding.id,
        catalog_entry_id=entry.id,
        model_revision=entry.model_revision,
        manifest_hash=entry.contract_manifest_hash,
        invoke_model_value=binding.invoke_model_value,
        connection_id=connection.id,
        connection_revision_id=original_revision.id,
        credential_revision_id=original_revision.credential_revision_id,
        capability="image.generate",
        mode_id="text_to_image",
        effective_options={},
        resolved_references=[],
        translation_report={},
        request_fingerprint="f" * 64,
    )
    identity_json = identity.model_dump(mode="json")
    run.input_snapshot = {"execution_identity": identity_json}
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
        request_summary={"kind": "keyframe", "execution_identity": identity_json},
        response_summary={},
        submitted_at=None,
        provider_operation_id="uni-img-1",
        connection_id=connection_id,
        provider_connection_revision_id=original_revision.id,
        selection_plan={
            "execution_identity": identity_json,
            "execution_model_resolution": {
                "requested_model_id": "uni-img-model",
                "resolved_model_id": "uni-img-model",
                "source": "request_override",
                "status": "RESOLVED",
                "provider_model_binding_id": str(binding.id),
                "provider_connection_id": str(connection.id),
                "provider_connection_revision_id": str(original_revision.id),
                "credential_revision_id": str(original_revision.credential_revision_id),
                "catalog_entry_id": str(entry.id),
                "model_revision": entry.model_revision,
                "manifest_hash": entry.contract_manifest_hash,
                "invoke_model_value": binding.invoke_model_value,
                "capability": "image.generate",
                "mode_id": "text_to_image",
                "native_options": {},
            },
        },
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

    from app.providers.connection_service import ProviderConnectionService

    await ProviderConnectionService(session).update_connection(
        workspace_id=_workspace.id,
        connection_id=connection.id,
        actor=user,
        display_name=None,
        enabled=None,
        base_url="https://connection-revision-two.example",
    )
    current_revision = await session.scalar(
        select(ProviderConnectionRevision)
        .where(ProviderConnectionRevision.connection_id == connection.id)
        .order_by(ProviderConnectionRevision.revision_no.desc())
        .limit(1)
    )
    assert current_revision is not None
    assert current_revision.id != original_revision.id

    await ProviderConnectionService(session).update_credential(
        workspace_id=_workspace.id,
        connection_id=connection.id,
        actor=user,
        api_key="uni-secret-revision-two",
    )
    latest_revision = await session.scalar(
        select(ProviderConnectionRevision)
        .where(ProviderConnectionRevision.connection_id == connection.id)
        .order_by(ProviderConnectionRevision.revision_no.desc())
        .limit(1)
    )
    assert latest_revision is not None and latest_revision.id != original_revision.id

    result = await execute_media_node_run(session, node_run_id=run.id)
    assert result.node_type == "keyframe"
    # Resume must never call submit again.
    assert _current_runtime().submit_calls == 0
    assert _current_runtime().poll_calls >= 1
    refreshed = await session.get(ProviderOperation, op.id)
    assert refreshed is not None and refreshed.status == "succeeded"
    assert refreshed.provider_connection_revision_id == original_revision.id
    frozen_runtime = _current_runtime()
    assert frozen_runtime.factory_connection.base_url == original_revision.base_url
    assert frozen_runtime.factory_settings.unified_test_api_key == "uni-secret"


@pytest.mark.asyncio
async def test_heavy_worker_startup_requeues_persisted_remote_poll(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import AbstractAsyncContextManager
    from unittest.mock import AsyncMock

    from app.runtime.scheduler import AgentRunScheduler
    from app.workers.jobs import recover_interrupted_provider_jobs

    _byok(monkeypatch)
    _user, _workspace, run = await _seed_project_chain(session)
    run.status = "running"
    run.input_snapshot = {
        **run.input_snapshot,
        "source_commit": "resume-candidate",
        "dispatch_generation": "initial-submit",
    }
    operation = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="video.generate",
        actual_provider=FAKE_PROVIDER,
        actual_model="uni-vid-model",
        protocol_profile=FAKE_PROFILE,
        request_fingerprint="f" * 64,
        status="submitted",
        request_summary={},
        response_summary={},
        provider_operation_id="remote-video-1",
        execution_path_version=UNIFIED_PATH_VERSION,
    )
    session.add(operation)
    await session.commit()

    class ExistingSessionContext(AbstractAsyncContextManager[AsyncSession]):
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

    enqueue = AsyncMock(return_value="resume-job")
    monkeypatch.setattr(
        "app.workers.jobs.get_session_factory",
        lambda: lambda: ExistingSessionContext(),
    )
    monkeypatch.setattr(AgentRunScheduler, "enqueue_node_run_only", enqueue)

    await recover_interrupted_provider_jobs({})

    await session.refresh(run)
    await session.refresh(operation)
    assert run.status == "queued"
    assert run.input_snapshot["provider_poll_resume_count"] == 1
    assert str(run.input_snapshot["dispatch_generation"]).startswith(
        f"provider-resume-{str(operation.id)[:12]}-"
    )
    assert operation.provider_operation_id == "remote-video-1"
    assert operation.attempt_no == 1
    enqueue.assert_awaited_once_with(run.id)


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
    user, workspace, run = await _seed_project_chain(session)

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
    assert op.provider_connection_revision_id is not None
    frozen_revision = await session.get(
        ProviderConnectionRevision, op.provider_connection_revision_id
    )
    assert frozen_revision is not None

    # A rejected create has no remote task and may be resubmitted, but it is
    # still the same execution: current connection/credential changes must not
    # replace its already-frozen revision.
    from app.providers.connection_service import ProviderConnectionService

    connection = await session.get(ProviderConnection, op.connection_id)
    assert connection is not None
    await ProviderConnectionService(session).update_connection(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        display_name=None,
        enabled=None,
        base_url="https://retry-revision-two.example",
    )
    await ProviderConnectionService(session).update_credential(
        workspace_id=workspace.id,
        connection_id=connection.id,
        actor=user,
        api_key="uni-secret-retry-revision-two",
    )

    # Scheduler requeues the run; the retry resubmits the same op (no duplicate).
    run.status = "queued"
    await session.flush()
    result = await execute_media_node_run(session, node_run_id=run.id)
    assert result.node_type == "keyframe"
    refreshed = await session.get(ProviderOperation, op.id)
    assert refreshed is not None
    assert refreshed.status == "succeeded"
    assert refreshed.provider_operation_id == "uni-img-1"
    assert refreshed.provider_connection_revision_id == frozen_revision.id
    assert _current_runtime().factory_connection.base_url == frozen_revision.base_url
    assert _current_runtime().factory_settings.unified_test_api_key == "uni-secret"
    # Exactly two submission attempts total (one refused, one accepted).
    assert _current_runtime().submit_calls == 1
    ops = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalars().all()
    assert len(ops) == 1
