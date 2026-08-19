"""Accepted repair evidence must replace only its root batch shots."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.director.enums import ArtifactKind, WorkflowStatus
from app.director.models import (
    ApprovalRecord,
    BudgetAuthorization,
    CreativeArtifactVersion,
    DirectorWorkflowRun,
    ProductionBatch,
    ProductionBatchShot,
)
from app.director.quality_service import DirectorQualityService
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as value:
        yield value
    await engine.dispose()


def _quality_payload(*, batch_id: object, logical_shot_id: str) -> dict[str, object]:
    dimensions = [
        {
            "dimension": dimension,
            "status": "passed",
            "summary": f"{dimension} evidence accepted for creator review",
            "evidence_refs": [f"evidence:{dimension}"],
            "signals": {},
        }
        for dimension in (
            "request_contract",
            "identity",
            "technical_integrity",
            "voice_assignment",
            "mouth_motion",
            "continuity",
            "narrative_and_performance",
        )
    ]
    report = {
        "policy_id": "live-dialogue-quality-v1",
        "batch_id": str(batch_id),
        "logical_shot_id": logical_shot_id,
        "overall_status": "passed",
        "dimensions": dimensions,
        "hard_blockers": [],
        "limitations": [],
        "recommended_action": "accept",
    }
    return {
        "policy_id": "live-dialogue-quality-v1",
        "batch_id": str(batch_id),
        "shot_reports": [report],
        "overall_status": "passed",
        "hard_blockers": [],
    }


async def _seed_repair_review(
    session: AsyncSession, *, root_kind: str
) -> tuple[
    User,
    Project,
    DirectorWorkflowRun,
    ProductionBatch,
    ProductionBatchShot,
    ProductionBatch,
    ProductionBatchShot,
    CreativeArtifactVersion,
]:
    user = User(
        email=f"repair-{root_kind}-{uuid4().hex[:8]}@example.com",
        display_name="Creator",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="Repair review")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Repairable short",
        aspect_ratio="9:16",
        budget_limit=Decimal("100"),
        budget_currency="CNY",
    )
    session.add(project)
    await session.flush()
    workflow = DirectorWorkflowRun(
        project_id=project.id,
        template_id="live_action_dialogue_short",
        template_version="1.0.0",
        status=WorkflowStatus.FINAL_REVIEW.value,
        current_stage="production",
        current_artifact_versions={},
        created_by=user.id,
    )
    session.add(workflow)
    await session.flush()
    auth = BudgetAuthorization(
        project_id=project.id,
        workflow_run_id=workflow.id,
        authorization_kind="repair_budget",
        idempotency_key=f"repair-budget-{root_kind}",
        pricing_snapshot_id="verified-repair-price",
        limit_amount=Decimal("10"),
        consumed_amount=Decimal("1"),
        currency="CNY",
        status="active",
        authorized_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(auth)
    await session.flush()
    root = ProductionBatch(
        project_id=project.id,
        workflow_run_id=workflow.id,
        batch_kind=root_kind,
        idempotency_key=f"root-{root_kind}",
        status="repair_requested",
        budget_authorization_id=auth.id,
        locked_version_refs={},
        selected_shot_ids=["shot-1"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={},
        semantic_hash=hashlib.sha256(f"root-{root_kind}".encode()).hexdigest(),
        created_by=user.id,
    )
    session.add(root)
    await session.flush()
    root_shot = ProductionBatchShot(
        project_id=project.id,
        batch_id=root.id,
        logical_shot_id="shot-1",
        status="repair_requested",
        semantic_hash=hashlib.sha256(b"old-shot").hexdigest(),
    )
    session.add(root_shot)
    repair = ProductionBatch(
        project_id=project.id,
        workflow_run_id=workflow.id,
        batch_kind="repair",
        idempotency_key=f"repair-{root_kind}",
        status="awaiting_review",
        budget_authorization_id=auth.id,
        locked_version_refs={},
        selected_shot_ids=["shot-1"],
        template_keys=["dialogue-post-dub-shot-v1"],
        quality_policy_id="live-dialogue-quality-v1",
        selection_snapshot={
            "source_batch_id": str(root.id),
            "root_source_batch_id": str(root.id),
        },
        semantic_hash=hashlib.sha256(f"repair-{root_kind}".encode()).hexdigest(),
        created_by=user.id,
    )
    session.add(repair)
    await session.flush()
    accepted_artifact_id = uuid4()
    accepted_run_id = uuid4()
    repair_shot = ProductionBatchShot(
        project_id=project.id,
        batch_id=repair.id,
        logical_shot_id="shot-1",
        status="ready_for_review",
        semantic_hash=hashlib.sha256(b"repaired-shot").hexdigest(),
        accepted_artifact_id=accepted_artifact_id,
        accepted_node_run_id=accepted_run_id,
    )
    session.add(repair_shot)
    quality = CreativeArtifactVersion(
        project_id=project.id,
        workflow_run_id=workflow.id,
        artifact_kind=ArtifactKind.QUALITY_REPORT.value,
        revision_no=1,
        source_kind="service",
        payload=_quality_payload(batch_id=repair.id, logical_shot_id="shot-1"),
        content_hash=hashlib.sha256(f"quality-{root_kind}".encode()).hexdigest(),
        status="draft",
        created_by=user.id,
    )
    session.add(quality)
    await session.flush()
    workflow.current_artifact_versions = {ArtifactKind.QUALITY_REPORT.value: str(quality.id)}
    await session.commit()
    return user, project, workflow, root, root_shot, repair, repair_shot, quality


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("root_kind", "expected_status"),
    [
        ("production", WorkflowStatus.ASSEMBLING.value),
        ("trial", WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION.value),
    ],
)
async def test_accepting_repair_propagates_exact_composite_to_root_batch(
    session: AsyncSession,
    root_kind: str,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, project, workflow, root, root_shot, repair, repair_shot, quality = (
        await _seed_repair_review(session, root_kind=root_kind)
    )

    promoted_batches: list[UUID] = []

    async def record_canonical_promotion(
        _service: DirectorQualityService, *, batch: ProductionBatch
    ) -> None:
        promoted_batches.append(batch.id)

    monkeypatch.setattr(
        DirectorQualityService,
        "_promote_trial_canonical_set",
        record_canonical_promotion,
    )
    result = await DirectorQualityService(session).review_production(
        project_id=project.id,
        batch_id=repair.id,
        decisions={"shot-1": "accept"},
        user_note="The repaired shot now matches my intent.",
        actor=user,
        idempotency_key=f"accept-repair-{root_kind}",
    )

    assert result.artifact_kind == ArtifactKind.PRODUCTION_REVIEW.value
    assert repair.status == "accepted"
    assert root.status == "accepted"
    assert root_shot.status == "accepted"
    assert root_shot.accepted_artifact_id == repair_shot.accepted_artifact_id
    assert root_shot.accepted_node_run_id == repair_shot.accepted_node_run_id
    assert root_shot.semantic_hash == repair_shot.semantic_hash
    assert workflow.status == expected_status
    if root_kind == "trial":
        assert promoted_batches == [root.id]
        trial_review_id = workflow.current_artifact_versions.get(
            ArtifactKind.TRIAL_REVIEW.value
        )
        assert trial_review_id is not None
        trial_review = await session.get(CreativeArtifactVersion, UUID(trial_review_id))
        assert trial_review is not None
        assert trial_review.payload["batch_id"] == str(root.id)
        assert trial_review.payload["accepted_quality"] is True
        assert trial_review.payload["quality_report_version_id"] == str(quality.id)
    else:
        assert promoted_batches == []


@pytest.mark.asyncio
async def test_subjective_accept_requires_reason_and_records_override(
    session: AsyncSession,
) -> None:
    user, project, workflow, root, root_shot, repair, repair_shot, quality = (
        await _seed_repair_review(session, root_kind="production")
    )
    payload = dict(quality.payload)
    shot_report = dict(payload["shot_reports"][0])
    dimensions = [dict(item) for item in shot_report["dimensions"]]
    dimensions[1]["status"] = "needs_human"
    shot_report["dimensions"] = dimensions
    shot_report["overall_status"] = "needs_human"
    shot_report["recommended_action"] = "review"
    payload["shot_reports"] = [shot_report]
    payload["overall_status"] = "needs_human"
    quality.payload = payload
    await session.commit()
    project_id = project.id
    repair_id = repair.id
    quality_id = quality.id
    user_id = user.id

    with pytest.raises(ValidationAppError) as caught:
        await DirectorQualityService(session).review_production(
            project_id=project_id,
            batch_id=repair_id,
            decisions={"shot-1": "accept"},
            user_note="",
            actor=user,
            idempotency_key="subjective-without-reason",
        )
    assert caught.value.details["code"] == "SUBJECTIVE_OVERRIDE_REASON_REQUIRED"
    await session.rollback()
    user = await session.get(User, user_id)
    assert user is not None

    await DirectorQualityService(session).review_production(
        project_id=project_id,
        batch_id=repair_id,
        decisions={"shot-1": "accept"},
        user_note="The identity and performance are acceptable for this story.",
        actor=user,
        idempotency_key="subjective-with-reason",
    )
    override = await session.scalar(
        select(ApprovalRecord).where(
            ApprovalRecord.project_id == project_id,
            ApprovalRecord.approval_kind == "subjective_gate_override",
        )
    )
    assert override is not None
    assert override.approved_artifact_versions == {"quality_report": str(quality_id)}
    assert override.approved_by == user_id
    assert "The identity and performance are acceptable" in (override.reason or "")
    assert "Scope:" in (override.reason or "")
    assert "shot-1" in (override.reason or "")
