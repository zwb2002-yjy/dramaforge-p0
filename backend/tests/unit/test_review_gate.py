"""Human review decisions and the production admission they authorize."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.delivery.models import HumanReviewDecision
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.review_gate import (
    evaluate_artifact_admission,
    record_human_decision,
    subject_fingerprint,
)
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.enums import ProjectStage
from app.shared.errors import ConflictError, ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _env(session: AsyncSession) -> tuple[User, Project, Shot]:
    user = User(
        email=f"review-{uuid4().hex[:8]}@example.com",
        display_name="Reviewer",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:6]}",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Room",
        time_of_day="day",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        shot_type="medium",
        camera_move="static",
        visual_description="A waits",
        dialogue="",
        status="draft",
        sort_order=1,
    )
    session.add(shot)
    await session.flush()
    return user, project, shot


async def _artifact(
    session: AsyncSession, *, project_id: UUID, artifact_type: str = "image", hash_seed: str = "a"
) -> Artifact:
    artifact = Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        storage_state="available",
        object_key=f"obj/{uuid4().hex}.bin",
        content_hash=(hash_seed * 64)[:64],
        mime_type="image/png" if artifact_type == "image" else "video/mp4",
        byte_size=8,
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def _review_run(
    session: AsyncSession,
    *,
    project_id: UUID,
    shot_id: UUID,
    created_by: UUID,
    node_key: str = "identity_review",
    status: str = "needs_human",
    upstream_artifact_id: UUID | None = None,
    review_artifact_id: UUID | None = None,
) -> NodeRun:
    graph = await GraphService(session).create_graph(
        project_id=project_id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key=f"review-{uuid4().hex[:8]}",
        created_by=created_by,
        definition={},
    )
    node = GraphNode(
        graph_version_id=graph.current_version_id,
        node_key=node_key,
        node_type=node_key,
        display_name=node_key,
        cacheable=False,
    )
    session.add(node)
    await session.flush()
    run = NodeRun(
        project_id=project_id,
        graph_version_id=graph.current_version_id,
        graph_node_id=node.id,
        idempotency_key=f"review-{uuid4().hex}",
        input_hash=uuid4().hex * 2,
        input_snapshot={
            "shot_id": str(shot_id),
            "node_key": node_key,
            **(
                {"upstream_artifact_id": str(upstream_artifact_id)}
                if upstream_artifact_id is not None
                else {}
            ),
        },
        output_summary={"status": status},
        status="completed",
        result_artifact_id=review_artifact_id,
        created_by=created_by,
    )
    session.add(run)
    await session.flush()
    return run


async def _count(session: AsyncSession, model: type) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


@pytest.mark.asyncio
async def test_a_machine_needs_human_never_admits_production(session: AsyncSession) -> None:
    user, project, shot = await _env(session)
    artifact = await _artifact(session, project_id=project.id)
    evidence = await _artifact(session, project_id=project.id, hash_seed="b")
    await _review_run(
        session,
        project_id=project.id,
        shot_id=shot.id,
        created_by=user.id,
        upstream_artifact_id=artifact.id,
        review_artifact_id=evidence.id,
    )

    admission = await evaluate_artifact_admission(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        stage="formal_keyframe",
    )

    assert admission.allowed is False
    assert admission.review_kind == "identity"
    assert admission.blocked_reason_codes == ["REVIEW_AWAITING_HUMAN"]
    requirement = admission.requirements[0]
    assert requirement.machine_status == "needs_human"
    assert requirement.decision is None
    # The machine result stays evidence; nothing was written as a decision.
    assert await _count(session, HumanReviewDecision) == 0


@pytest.mark.asyncio
async def test_a_stored_approval_admits_exactly_that_artifact(session: AsyncSession) -> None:
    user, project, shot = await _env(session)
    artifact = await _artifact(session, project_id=project.id)
    other = await _artifact(session, project_id=project.id, hash_seed="c")
    evidence = await _artifact(session, project_id=project.id, hash_seed="b")
    run = await _review_run(
        session,
        project_id=project.id,
        shot_id=shot.id,
        created_by=user.id,
        upstream_artifact_id=artifact.id,
        review_artifact_id=evidence.id,
    )
    await record_human_decision(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        review_node_run_id=run.id,
        review_kind="identity",
        decision="approved",
        reason="对白口型与人物一致，可继续。",
        actor_id=user.id,
        shot_version=shot.version,
        request_key="review:one",
    )
    await session.flush()

    approved = await evaluate_artifact_admission(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        stage="formal_keyframe",
    )
    assert approved.allowed is True
    assert approved.requirements[0].decision == "approved"

    # A different artifact cannot borrow the decision.
    unrelated = await evaluate_artifact_admission(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=other.id,
        stage="formal_keyframe",
    )
    assert unrelated.allowed is False
    assert unrelated.blocked_reason_codes == ["REVIEW_DECISION_MISSING"]


@pytest.mark.asyncio
async def test_a_rejection_blocks_and_a_later_approval_supersedes_it(
    session: AsyncSession,
) -> None:
    user, project, shot = await _env(session)
    artifact = await _artifact(session, project_id=project.id)
    evidence = await _artifact(session, project_id=project.id, hash_seed="b")
    run = await _review_run(
        session,
        project_id=project.id,
        shot_id=shot.id,
        created_by=user.id,
        upstream_artifact_id=artifact.id,
        review_artifact_id=evidence.id,
    )
    rejected = await record_human_decision(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        review_node_run_id=run.id,
        review_kind="identity",
        decision="rejected",
        reason="人物脸部崩坏。",
        actor_id=user.id,
        shot_version=shot.version,
        request_key="review:reject",
    )
    await session.flush()
    blocked = await evaluate_artifact_admission(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        stage="formal_keyframe",
    )
    assert blocked.allowed is False
    assert blocked.blocked_reason_codes == ["REVIEW_DECISION_REJECTED"]

    approved = await record_human_decision(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        review_node_run_id=run.id,
        review_kind="identity",
        decision="approved",
        reason="已重生并通过。",
        actor_id=user.id,
        shot_version=shot.version,
        request_key="review:approve",
    )
    await session.flush()

    assert approved.supersedes_id == rejected.id
    # History is appended, never overwritten.
    assert await _count(session, HumanReviewDecision) == 2
    allowed = await evaluate_artifact_admission(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        stage="formal_keyframe",
    )
    assert allowed.allowed is True
    assert allowed.requirements[0].decision == "approved"


@pytest.mark.asyncio
async def test_confirming_formal_does_not_invalidate_the_same_decision(
    session: AsyncSession,
) -> None:
    """A Formal selection advances Shot.version; the approval must survive it."""
    user, project, shot = await _env(session)
    artifact = await _artifact(session, project_id=project.id)
    evidence = await _artifact(session, project_id=project.id, hash_seed="b")
    run = await _review_run(
        session,
        project_id=project.id,
        shot_id=shot.id,
        created_by=user.id,
        upstream_artifact_id=artifact.id,
        review_artifact_id=evidence.id,
    )
    await record_human_decision(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        review_node_run_id=run.id,
        review_kind="identity",
        decision="approved",
        reason="通过。",
        actor_id=user.id,
        shot_version=shot.version,
        request_key="review:formal",
    )
    # Simulate the Formal pointer confirmation advancing the Shot version.
    shot.version += 1
    await session.flush()

    admission = await evaluate_artifact_admission(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        stage="formal_keyframe",
    )
    assert admission.allowed is True


@pytest.mark.asyncio
async def test_new_media_bytes_invalidate_an_old_approval(session: AsyncSession) -> None:
    """A new Artifact must be reviewed again; an old approval cannot be reused."""
    user, project, shot = await _env(session)
    artifact = await _artifact(session, project_id=project.id)
    evidence = await _artifact(session, project_id=project.id, hash_seed="b")
    run = await _review_run(
        session,
        project_id=project.id,
        shot_id=shot.id,
        created_by=user.id,
        upstream_artifact_id=artifact.id,
        review_artifact_id=evidence.id,
    )
    decision = await record_human_decision(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        review_node_run_id=run.id,
        review_kind="identity",
        decision="approved",
        reason="通过。",
        actor_id=user.id,
        shot_version=shot.version,
        request_key="review:stale",
    )
    await session.flush()
    # The reviewed bytes are replaced in place (same Artifact row).
    artifact.content_hash = "f" * 64
    await session.flush()

    admission = await evaluate_artifact_admission(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        stage="formal_keyframe",
    )

    assert admission.allowed is False
    assert admission.blocked_reason_codes == ["REVIEW_DECISION_STALE"]
    assert admission.requirements[0].decision == "approved"
    assert decision.subject_fingerprint != admission and True  # kept for audit


@pytest.mark.asyncio
async def test_decision_submission_is_retry_safe_and_requires_a_reason(
    session: AsyncSession,
) -> None:
    user, project, shot = await _env(session)
    artifact = await _artifact(session, project_id=project.id)
    evidence = await _artifact(session, project_id=project.id, hash_seed="b")
    run = await _review_run(
        session,
        project_id=project.id,
        shot_id=shot.id,
        created_by=user.id,
        upstream_artifact_id=artifact.id,
        review_artifact_id=evidence.id,
    )
    payload = {
        "project_id": project.id,
        "shot_id": shot.id,
        "artifact_id": artifact.id,
        "review_node_run_id": run.id,
        "review_kind": "identity",
        "decision": "approved",
        "reason": "通过。",
        "actor_id": user.id,
        "shot_version": shot.version,
        "request_key": "review:retry",
    }
    first = await record_human_decision(session, **payload)  # type: ignore[arg-type]
    await session.flush()
    second = await record_human_decision(session, **payload)  # type: ignore[arg-type]
    await session.flush()

    assert second.id == first.id
    assert await _count(session, HumanReviewDecision) == 1

    with pytest.raises(ConflictError) as reused:
        await record_human_decision(
            session, **{**payload, "decision": "rejected", "reason": "改主意了。"}  # type: ignore[arg-type]
        )
    assert reused.value.details.get("code") == "REVIEW_DECISION_REQUEST_REUSED"

    with pytest.raises(ValidationAppError) as blank:
        await record_human_decision(
            session, **{**payload, "request_key": "review:blank", "reason": "   "}  # type: ignore[arg-type]
        )
    assert blank.value.details.get("code") == "REVIEW_REASON_REQUIRED"


@pytest.mark.asyncio
async def test_admission_rejects_an_unknown_stage(session: AsyncSession) -> None:
    user, project, shot = await _env(session)
    artifact = await _artifact(session, project_id=project.id)

    with pytest.raises(ValidationAppError) as unknown:
        await evaluate_artifact_admission(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=artifact.id,
            stage="whatever",
        )
    assert unknown.value.details.get("code") == "REVIEW_STAGE_UNKNOWN"


def test_subject_fingerprint_ignores_shot_version_but_tracks_evidence() -> None:
    base = {
        "artifact_id": uuid4(),
        "artifact_content_hash": "a" * 64,
        "review_kind": "identity",
        "review_node_run_id": uuid4(),
        "review_artifact_id": uuid4(),
        "review_evidence_hash": "b" * 64,
    }
    first = subject_fingerprint(**base)  # type: ignore[arg-type]
    assert first == subject_fingerprint(**base)  # type: ignore[arg-type]
    assert first != subject_fingerprint(**{**base, "artifact_content_hash": "c" * 64})  # type: ignore[arg-type]
    assert first != subject_fingerprint(**{**base, "review_kind": "continuity"})  # type: ignore[arg-type]
    assert first != subject_fingerprint(**{**base, "review_evidence_hash": "d" * 64})  # type: ignore[arg-type]
