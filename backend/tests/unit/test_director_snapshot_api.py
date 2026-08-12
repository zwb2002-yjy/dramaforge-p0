"""Director aggregate snapshot survives refresh without frontend reconstruction."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.director.enums import ApprovalKind, ArtifactKind, AuthorizationStatus, WorkflowStatus
from app.director.models import (
    ApprovalRecord,
    BudgetAuthorization,
    BudgetReservation,
    CreativeArtifactVersion,
    DirectorWorkflowRun,
    ProductionBatch,
)
from app.director.service import DirectorService
from app.director.snapshot_service import DirectorSnapshotService
from app.execution.models import GraphNode, NodeRun
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import CSRF_HEADER, hash_password
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PostMediaChangeContext = tuple[
    User,
    Project,
    DirectorWorkflowRun,
    CreativeArtifactVersion,
    ProductionBatch,
    BudgetReservation,
    BudgetAuthorization,
    ApprovalRecord,
]


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as value:
        yield value
    await engine.dispose()


def test_snapshot_returns_current_payloads_and_allowed_actions(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": "snapshot@example.com", "password": "password123", "display_name": "S"},
        ).status_code
        == 201
    )
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    project = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Recoverable", "aspect_ratio": "9:16"},
        headers={CSRF_HEADER: _csrf(client)},
    ).json()
    project_id = project["id"]
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/director/workflow",
            json={},
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 201
    )
    concepts = client.post(
        f"/api/v1/projects/{project_id}/director/creative/concepts/generate",
        json={
            "entry_mode": "one_sentence",
            "idea": "two people finally tell the truth before one leaves",
            "authorize_text_call": True,
            "idempotency_key": "snapshot-concepts",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert concepts.status_code == 201, concepts.text

    first = client.get(f"/api/v1/projects/{project_id}/director/workspace-snapshot")
    second = client.get(f"/api/v1/projects/{project_id}/director/workspace-snapshot")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    body = first.json()
    assert body == second.json()
    assert body["project_name"] == "Recoverable"
    assert body["aspect_ratio"] == "9:16"
    assert body["current_artifacts"]["concept_set"]["id"] == concepts.json()["id"]
    assert len(body["current_artifacts"]["concept_set"]["payload"]["concepts"]) == 3
    assert body["allowed_actions"] == ["generate_concepts", "import_script"]
    assert body["production_batches"] == []
    assert body["budget_reservations"] == []


@pytest.mark.asyncio
async def test_snapshot_returns_shared_director_batch_and_reservation_lineage(
    session: AsyncSession,
) -> None:
    user = User(
        email=f"snapshot-lineage-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("password123"),
        display_name="Lineage",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Shared facts")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Shared facts",
        aspect_ratio="16:9",
        budget_limit=Decimal("10"),
        budget_currency="CNY",
    )
    session.add(project)
    await session.flush()
    workflow = DirectorWorkflowRun(
        project_id=project.id,
        template_id="live_action_dialogue_short",
        template_version="1.0.0",
        status=WorkflowStatus.TRIAL_RUNNING.value,
        current_stage="trial",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()
    storyboard = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.STORYBOARD_PLAN.value,
        revision_no=1,
        source_kind="agent",
        payload={"template_key": "live_action_dialogue_short_v1", "shots": []},
        content_hash=hashlib.sha256(b"shared-storyboard").hexdigest(),
        status="locked",
        created_by=user.id,
    )
    session.add(storyboard)
    await session.flush()
    workflow.current_artifact_versions = {ArtifactKind.STORYBOARD_PLAN.value: str(storyboard.id)}
    authorization = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind="trial_budget",
        idempotency_key="shared-trial-budget",
        pricing_snapshot_id="director-cost-snapshot-v1",
        limit_amount=Decimal("10"),
        consumed_amount=Decimal("0"),
        currency="CNY",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    batch = ProductionBatch(
        project_id=project.id,
        workflow_run_id=workflow.id,
        batch_kind="trial",
        idempotency_key="shared-trial-materialize",
        status="running",
        budget_authorization_id=authorization.id,
        locked_version_refs=workflow.current_artifact_versions,
        selected_shot_ids=["shot-2"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={"status": "ready"},
        semantic_hash=hashlib.sha256(b"shared-trial").hexdigest(),
        created_by=user.id,
    )
    session.add(batch)
    await session.flush()
    session.add(
        BudgetReservation(
            project_id=project.id,
            batch_id=batch.id,
            authorization_id=authorization.id,
            idempotency_key="shared-trial-reservation",
            reserved_amount=Decimal("3"),
            currency="CNY",
            status="reserved",
        )
    )
    await session.commit()

    snapshot = await DirectorSnapshotService(session).get(project_id=project.id, actor=user)

    assert snapshot.workflow.status == WorkflowStatus.TRIAL_RUNNING.value
    assert snapshot.current_artifacts[ArtifactKind.STORYBOARD_PLAN.value].revision_no == 1
    assert len(snapshot.production_batches) == 1
    returned_batch = snapshot.production_batches[0]
    assert returned_batch.batch_kind == "trial"
    assert returned_batch.selected_shot_ids == ["shot-2"]
    assert {reservation.batch_id for reservation in snapshot.budget_reservations} == {
        batch.id
    }
    assert {reservation.authorization_id for reservation in snapshot.budget_reservations} == {
        authorization.id
    }


async def _static_post_media_change_context(
    session: AsyncSession,
) -> PostMediaChangeContext:
    user = User(
        email=f"post-media-change-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("password123"),
        display_name="Revision owner",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Revision facts")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Post-media revision",
        aspect_ratio="9:16",
        budget_limit=Decimal("30"),
        budget_currency="CNY",
    )
    session.add(project)
    await session.flush()
    workflow = DirectorWorkflowRun(
        project_id=project.id,
        template_id="live_action_dialogue_short",
        template_version="1.0.0",
        status=WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION.value,
        current_stage="production",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()
    story = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.STORY_CORE.value,
        revision_no=1,
        source_kind="user",
        payload={
            "selected_concept_id": "concept-1",
            "theme": "诚实",
            "core_conflict": "主角必须在离开前说出真相",
            "emotional_direction": "克制到坦诚",
            "ending": "她留下来面对真相",
            "characters": [
                {
                    "name": "林夏",
                    "identity": "记者",
                    "desire": "得到真实答案",
                    "fear_or_cost": "失去离开的机会",
                }
            ],
        },
        content_hash=hashlib.sha256(b"post-media-story").hexdigest(),
        status="locked",
        created_by=user.id,
    )
    script = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.EPISODE_SCRIPT.value,
        revision_no=1,
        source_kind="user",
        payload={
            "title": "最后一句",
            "target_duration_seconds": 20,
            "setup": "林夏准备离开。",
            "turn": "对方终于说出真相。",
            "ending": "林夏决定听完再走。",
            "dialogue": [{"speaker": "林夏", "text": "你还有一句话。", "emotion": "克制"}],
        },
        content_hash=hashlib.sha256(b"post-media-script").hexdigest(),
        status="locked",
        created_by=user.id,
    )
    review = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.STORY_REVIEW.value,
        revision_no=1,
        source_kind="service",
        payload={
            "status": "passed",
            "logic_issues": [],
            "pacing_issues": [],
            "duration_risks": [],
            "closure_issues": [],
            "revision_suggestions": [],
        },
        content_hash=hashlib.sha256(b"post-media-review").hexdigest(),
        status="locked",
        created_by=user.id,
    )
    session.add_all([story, script, review])
    await session.flush()
    workflow.current_artifact_versions = {
        ArtifactKind.STORY_CORE.value: str(story.id),
        ArtifactKind.EPISODE_SCRIPT.value: str(script.id),
        ArtifactKind.STORY_REVIEW.value: str(review.id),
    }
    authorization = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind=ApprovalKind.TRIAL_BUDGET.value,
        idempotency_key="post-media-trial-budget",
        pricing_snapshot_id="post-media-price-v1",
        limit_amount=Decimal("3"),
        consumed_amount=Decimal("0"),
        currency="CNY",
        status=AuthorizationStatus.ACTIVE.value,
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(authorization)
    await session.flush()
    approval = ApprovalRecord(
        project_id=project.id,
        workflow_run_id=workflow.id,
        approval_kind=ApprovalKind.TRIAL_BUDGET.value,
        idempotency_key="post-media-trial-approval",
        approved_artifact_versions=dict(workflow.current_artifact_versions),
        budget_authorization_id=authorization.id,
        approved_by=user.id,
    )
    batch = ProductionBatch(
        project_id=project.id,
        workflow_run_id=workflow.id,
        batch_kind="trial",
        idempotency_key="post-media-trial-batch",
        status="accepted",
        budget_authorization_id=authorization.id,
        locked_version_refs=dict(workflow.current_artifact_versions),
        selected_shot_ids=["shot-1"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={"source": "test"},
        semantic_hash=hashlib.sha256(b"post-media-batch").hexdigest(),
        created_by=user.id,
    )
    session.add_all([approval, batch])
    await session.flush()
    reservation = BudgetReservation(
        project_id=project.id,
        batch_id=batch.id,
        authorization_id=authorization.id,
        idempotency_key="post-media-trial-reservation",
        reserved_amount=Decimal("3"),
        currency="CNY",
        status="reserved",
    )
    session.add(reservation)
    await session.commit()
    return user, project, workflow, story, batch, reservation, authorization, approval


@pytest.mark.asyncio
async def test_confirmed_post_media_change_supersedes_lineage_and_releases_unused_budget(
    session: AsyncSession,
) -> None:
    user, project, workflow, story, batch, reservation, authorization, approval = (
        await _static_post_media_change_context(session)
    )
    service = DirectorService(session)
    proposal, impact = await service.propose_change(
        project_id=project.id,
        actor=user,
        idempotency_key="post-media-story-change",
        target_artifact_kind=ArtifactKind.STORY_CORE,
        summary="把结局改成开放式",
        replacement_payload={**story.payload, "ending": "她暂时留下，等一个答案。"},
    )

    assert impact.affected_shot_ids == ["shot-1"]
    assert impact.reusable_artifact_ids == []
    assert impact.details["affected_batch_ids"] == [str(batch.id)]
    assert impact.details["releasable_reservation_ids"] == [str(reservation.id)]
    assert impact.details["historical_settled_amount"] == "0"
    assert impact.details["media_reuse_policy"] == "none_until_regenerated_and_reapproved"

    revised = await service.apply_change(
        project_id=project.id,
        proposal_id=proposal.id,
        actor=user,
    )
    await session.refresh(workflow)
    await session.refresh(story)
    await session.refresh(batch)
    await session.refresh(reservation)
    await session.refresh(authorization)
    await session.refresh(approval)

    assert revised.revision_no == 2
    assert story.status == "superseded"
    assert batch.status == "superseded_by_change"
    assert reservation.status == "released"
    assert reservation.actual_amount is None
    assert authorization.status == AuthorizationStatus.REVOKED.value
    assert approval.invalidated_at is not None
    assert workflow.status == WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION.value
    assert workflow.current_artifact_versions == {ArtifactKind.STORY_CORE.value: str(revised.id)}


@pytest.mark.asyncio
async def test_post_media_change_preserves_settled_cost_history(
    session: AsyncSession,
) -> None:
    user, project, _workflow, story, _batch, reservation, authorization, _approval = (
        await _static_post_media_change_context(session)
    )
    reservation.actual_amount = Decimal("1.25")
    reservation.settled_at = datetime.now(UTC)
    authorization.consumed_amount = Decimal("1.25")
    await session.commit()

    proposal, _impact = await DirectorService(session).propose_change(
        project_id=project.id,
        actor=user,
        idempotency_key="settled-post-media-story-change",
        target_artifact_kind=ArtifactKind.STORY_CORE,
        summary="保留历史成本后修改故事",
        replacement_payload={**story.payload, "ending": "她暂时离开，留下回信。"},
    )
    await DirectorService(session).apply_change(
        project_id=project.id,
        proposal_id=proposal.id,
        actor=user,
    )
    await session.refresh(reservation)
    await session.refresh(authorization)

    assert reservation.status == "reserved"
    assert reservation.actual_amount == Decimal("1.25")
    assert authorization.consumed_amount == Decimal("1.25")
    assert authorization.status == AuthorizationStatus.REVOKED.value


@pytest.mark.asyncio
async def test_post_media_change_rejects_an_active_batch_before_creating_proposal(
    session: AsyncSession,
) -> None:
    user, project, workflow, story, batch, _reservation, _authorization, _approval = (
        await _static_post_media_change_context(session)
    )
    batch.status = "running"
    await session.commit()

    with pytest.raises(ValidationAppError) as exc_info:
        await DirectorService(session).propose_change(
            project_id=project.id,
            actor=user,
            idempotency_key="blocked-post-media-change",
            target_artifact_kind=ArtifactKind.STORY_CORE,
            summary="不应改动运行中的试拍",
            replacement_payload={**story.payload, "ending": "不应写入"},
        )

    assert exc_info.value.details["code"] == "POST_MEDIA_CHANGE_ACTIVE_BATCH"
    assert exc_info.value.details["batch_ids"] == [str(batch.id)]


@pytest.mark.asyncio
async def test_post_media_change_rejects_an_active_node_run_before_creating_proposal(
    session: AsyncSession,
) -> None:
    user, project, _workflow, story, batch, _reservation, _authorization, _approval = (
        await _static_post_media_change_context(session)
    )
    graph = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="post-media-change-test",
        created_by=user.id,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="Keyframe",
    )
    session.add(node)
    await session.flush()
    session.add(
        NodeRun(
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            graph_node_id=node.id,
            production_batch_id=batch.id,
            attempt_no=1,
            idempotency_key="post-media-active-node",
            input_hash="a" * 64,
            status="queued",
            input_snapshot={},
            created_by=user.id,
        )
    )
    await session.commit()

    with pytest.raises(ValidationAppError) as exc_info:
        await DirectorService(session).propose_change(
            project_id=project.id,
            actor=user,
            idempotency_key="blocked-post-media-node",
            target_artifact_kind=ArtifactKind.STORY_CORE,
            summary="不应改动队列中的试拍",
            replacement_payload={**story.payload, "ending": "不应写入"},
        )

    assert exc_info.value.details["code"] == "POST_MEDIA_CHANGE_ACTIVE_NODE_RUN"
