"""Paid media execution must preserve Director budget and model lineage."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.director.execution_guard import (
    DirectorExecutionGuardError,
    settle_director_media_cost,
    validate_director_media_submission,
)
from app.director.models import (
    BudgetAuthorization,
    BudgetReservation,
    DirectorWorkflowRun,
    ProductionBatch,
)
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.execution.product_path import (
    _bind_director_canonical_source,
    _read_bound_artifact,
)
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _base_run(
    session: AsyncSession,
) -> tuple[User, NodeRun, GraphNode]:
    user = User(
        email=f"guard-{uuid4().hex}@example.com",
        display_name="Guard",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Guard")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name="Guard",
        aspect_ratio="9:16",
        actor=user,
    )
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="director-guard-test",
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
        idempotency_key=f"guard:{uuid4()}",
        input_hash="a" * 64,
        status="queued",
        input_snapshot={"purpose": "keyframe"},
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    return user, run, node


async def _attach_director_context(
    session: AsyncSession,
    *,
    user: User,
    run: NodeRun,
) -> tuple[DirectorWorkflowRun, ProductionBatch, BudgetReservation]:
    binding_id = uuid4()
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
        currency="CNY",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    selection = {
        "plans": [
            {
                "purpose": "keyframe",
                "model_binding_id": str(binding_id),
            }
        ]
    }
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
        selection_snapshot=selection,
        semantic_hash="b" * 64,
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
        currency="CNY",
        status="reserved",
    )
    session.add(reservation)
    await session.flush()
    run.production_batch_id = batch.id
    run.budget_reservation_id = reservation.id
    run.input_snapshot = {
        **(run.input_snapshot or {}),
        "workflow_run_id": str(workflow.id),
        "production_batch_id": str(batch.id),
        "budget_reservation_id": str(reservation.id),
        "model_binding_id": str(binding_id),
        "selection_plan": {
            "purpose": "keyframe",
            "model_binding_id": str(binding_id),
        },
    }
    await session.flush()
    return workflow, batch, reservation


@pytest.mark.asyncio
async def test_legacy_project_does_not_require_director_budget_context(
    session: AsyncSession,
) -> None:
    _user, run, node = await _base_run(session)

    assert await validate_director_media_submission(session, run=run, node=node) is None


@pytest.mark.asyncio
async def test_director_paid_run_requires_batch_and_reservation(
    session: AsyncSession,
) -> None:
    user, run, node = await _base_run(session)
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

    with pytest.raises(DirectorExecutionGuardError) as caught:
        await validate_director_media_submission(session, run=run, node=node)
    assert caught.value.code == "DIRECTOR_PRODUCTION_CONTEXT_REQUIRED"


@pytest.mark.asyncio
async def test_director_paid_run_uses_frozen_authorized_context(
    session: AsyncSession,
) -> None:
    user, run, node = await _base_run(session)
    workflow, batch, reservation = await _attach_director_context(
        session,
        user=user,
        run=run,
    )

    context = await validate_director_media_submission(session, run=run, node=node)

    assert context is not None
    assert context.workflow_run_id == workflow.id
    assert context.production_batch_id == batch.id
    assert context.budget_reservation_id == reservation.id
    assert str(context.model_binding_id) == run.input_snapshot["model_binding_id"]


@pytest.mark.asyncio
async def test_director_paid_run_rejects_expired_authorization_and_binding_drift(
    session: AsyncSession,
) -> None:
    user, run, node = await _base_run(session)
    _workflow, batch, _reservation = await _attach_director_context(
        session,
        user=user,
        run=run,
    )
    authorization = await session.get(BudgetAuthorization, batch.budget_authorization_id)
    assert authorization is not None
    authorization.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()
    with pytest.raises(DirectorExecutionGuardError) as caught:
        await validate_director_media_submission(session, run=run, node=node)
    assert caught.value.code == "DIRECTOR_BUDGET_AUTHORIZATION_INACTIVE"

    authorization.expires_at = datetime.now(UTC) + timedelta(hours=1)
    run.input_snapshot = {
        **run.input_snapshot,
        "model_binding_id": str(uuid4()),
    }
    await session.flush()
    with pytest.raises(DirectorExecutionGuardError) as caught:
        await validate_director_media_submission(session, run=run, node=node)
    assert caught.value.code == "DIRECTOR_MODEL_BINDING_SNAPSHOT_MISMATCH"


@pytest.mark.asyncio
async def test_director_paid_run_rejects_superseded_change_lineage(
    session: AsyncSession,
) -> None:
    user, run, node = await _base_run(session)
    _workflow, batch, reservation = await _attach_director_context(
        session,
        user=user,
        run=run,
    )
    authorization = await session.get(BudgetAuthorization, batch.budget_authorization_id)
    assert authorization is not None
    batch.status = "superseded_by_change"
    reservation.status = "released"
    authorization.status = "revoked"
    await session.flush()

    with pytest.raises(DirectorExecutionGuardError) as caught:
        await validate_director_media_submission(session, run=run, node=node)

    assert caught.value.code == "DIRECTOR_PRODUCTION_CONTEXT_INVALID"
    assert caught.value.details["batch_status"] == "superseded_by_change"


@pytest.mark.asyncio
async def test_canonical_source_must_be_completed_image_in_same_batch(
    session: AsyncSession,
) -> None:
    user, run, _node = await _base_run(session)
    _workflow, _batch, reservation = await _attach_director_context(
        session,
        user=user,
        run=run,
    )
    source = NodeRun(
        project_id=run.project_id,
        graph_version_id=run.graph_version_id,
        graph_node_id=run.graph_node_id,
        production_batch_id=run.production_batch_id,
        budget_reservation_id=reservation.id,
        # ``_base_run`` already owns attempt 1 for this graph node; the
        # canonical source is a later execution attempt.
        attempt_no=2,
        idempotency_key=f"canonical:{uuid4()}",
        input_hash="c" * 64,
        status="completed",
        input_snapshot={},
        created_by=user.id,
    )
    session.add(source)
    await session.flush()
    store = InMemoryObjectStore()
    data = b"fictional-character-reference"
    stored = await store.put_bytes(
        object_key=f"projects/{run.project_id}/canonical.png",
        data=data,
        mime_type="image/png",
    )
    artifact = Artifact(
        project_id=run.project_id,
        artifact_type="image",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=hashlib.sha256(data).hexdigest(),
        mime_type="image/png",
        byte_size=len(data),
        produced_by_run_id=source.id,
    )
    session.add(artifact)
    await session.flush()
    source.result_artifact_id = artifact.id
    snapshot = {
        **run.input_snapshot,
        "canonical_source_run_id": str(source.id),
    }
    resolved = await _bind_director_canonical_source(
        session,
        run=run,
        snapshot=snapshot,
    )
    bound_artifact, bound_bytes = await _read_bound_artifact(
        session,
        run=run,
        snapshot=resolved,
        prefix="canonical",
        store=store,
        artifact_type="image",
    )
    assert bound_artifact.id == artifact.id
    assert bound_bytes == data

    reused_source = NodeRun(
        project_id=run.project_id,
        graph_version_id=run.graph_version_id,
        graph_node_id=run.graph_node_id,
        production_batch_id=run.production_batch_id,
        budget_reservation_id=reservation.id,
        attempt_no=3,
        idempotency_key=f"canonical-reused:{uuid4()}",
        input_hash="d" * 64,
        status="cached",
        input_snapshot={},
        result_artifact_id=artifact.id,
        reused_from_run_id=source.id,
        created_by=user.id,
    )
    session.add(reused_source)
    await session.flush()
    twice_reused_source = NodeRun(
        project_id=run.project_id,
        graph_version_id=run.graph_version_id,
        graph_node_id=run.graph_node_id,
        production_batch_id=run.production_batch_id,
        budget_reservation_id=reservation.id,
        attempt_no=4,
        idempotency_key=f"canonical-twice-reused:{uuid4()}",
        input_hash="e" * 64,
        status="cached",
        input_snapshot={},
        result_artifact_id=artifact.id,
        reused_from_run_id=reused_source.id,
        created_by=user.id,
    )
    session.add(twice_reused_source)
    await session.flush()
    resolved_from_chain = await _bind_director_canonical_source(
        session,
        run=run,
        snapshot={
            **run.input_snapshot,
            "canonical_source_run_id": str(twice_reused_source.id),
        },
    )
    assert resolved_from_chain["canonical_artifact_id"] == str(artifact.id)

    source.production_batch_id = uuid4()
    await session.flush()
    with pytest.raises(ValidationAppError, match="outside this Director production batch"):
        await _bind_director_canonical_source(
            session,
            run=run,
            snapshot={**snapshot, "canonical_artifact_id": None},
        )


@pytest.mark.asyncio
async def test_director_provider_cost_is_settled_once(
    session: AsyncSession,
) -> None:
    user, run, _node = await _base_run(session)
    _workflow, batch, reservation = await _attach_director_context(
        session,
        user=user,
        run=run,
    )
    operation = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="image.generate",
        actual_provider="fake",
        actual_model="fake-image",
        request_fingerprint="d" * 64,
        status="succeeded",
        request_summary={},
        response_summary={},
        provider_cost=Decimal("1.25"),
        currency="CNY",
    )
    session.add(operation)
    await session.flush()

    await settle_director_media_cost(session, run=run, operation=operation)
    await settle_director_media_cost(session, run=run, operation=operation)

    authorization = await session.get(BudgetAuthorization, batch.budget_authorization_id)
    await session.refresh(reservation)
    assert authorization is not None
    assert reservation.actual_amount == Decimal("1.25")
    assert authorization.consumed_amount == Decimal("1.25")
    assert operation.response_summary["director_budget_settled"] is True
