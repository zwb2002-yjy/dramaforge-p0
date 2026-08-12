"""Director aggregate snapshot survives refresh without frontend reconstruction."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.director.enums import ArtifactKind, WorkflowStatus
from app.director.models import (
    BudgetAuthorization,
    BudgetReservation,
    CreativeArtifactVersion,
    DirectorWorkflowRun,
    ProductionBatch,
)
from app.director.snapshot_service import DirectorSnapshotService
from app.shared.base import Base
from app.shared.security import CSRF_HEADER, hash_password
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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
