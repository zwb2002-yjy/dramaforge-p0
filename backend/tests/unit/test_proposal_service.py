"""P7-07 Proposal partial apply tests (03 §67)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.proposal_service import PartialApplyInput, ProposalDecision, ProposalService
from app.events.models import OutboxEvent
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from app.shared.security import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    load_all_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[Project, Shot, User]:
    user = User(
        email=f"apply-{uuid4().hex}@example.com",
        display_name="Apply",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        actor=user,
    )
    shot = Shot(
        project_id=project.id, scene_id=uuid4(), shot_number=1, version=1,
        visual_description="Shot", director_state={"camera": "static"},
        image_prompt="kf", video_prompt="video",
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


@pytest.mark.asyncio
async def test_partial_apply_only_executes_accepted(session: AsyncSession, monkeypatch) -> None:
    from app.director.business_checkpoints import DirectorBusinessCheckpoints

    def unavailable(*args, **kwargs):
        raise RuntimeError("Director is stopped")

    monkeypatch.setattr(DirectorBusinessCheckpoints, "__init__", unavailable)
    project, shot, user = await _seed(session)
    proposal = DirectorProposal(
        project_id=project.id, thread_id=uuid4(), scope_type="shot",
        scope_entity_id=shot.id, status="pending", created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    accept_item = DirectorProposalItem(
        proposal_id=proposal.id, project_id=project.id,
        command="shot.update_director_state",
        payload={"shot_id": str(shot.id), "director_state": {"camera": "low"}},
        expected_target_version=1, status="pending",
    )
    reject_item = DirectorProposalItem(
        proposal_id=proposal.id, project_id=project.id,
        command="shot.update_video_prompt",
        payload={"shot_id": str(shot.id), "video_prompt": "SHOULD NOT APPLY"},
        expected_target_version=1, status="pending",
    )
    session.add_all([accept_item, reject_item])
    await session.flush()

    result = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=proposal.id,
        apply_input=PartialApplyInput(
            decisions=[
                ProposalDecision(item_id=accept_item.id, decision="accepted"),
                ProposalDecision(item_id=reject_item.id, decision="rejected"),
            ]
        ),
    )
    await session.refresh(shot)
    assert shot.director_state == {"camera": "low"}  # accepted applied
    assert shot.video_prompt == "video"  # rejected NOT applied
    await session.refresh(accept_item)
    await session.refresh(reject_item)
    decided_version = shot.version
    replay = await ProposalService(session, actor=user).partial_apply(
        project=project, proposal_id=proposal.id,
        apply_input=PartialApplyInput(decisions=[
            ProposalDecision(item_id=accept_item.id, decision="accepted"),
            ProposalDecision(item_id=reject_item.id, decision="rejected"),
        ]),
    )
    await session.refresh(shot)
    assert replay.accepted == [accept_item.id] and replay.rejected == [reject_item.id]
    assert shot.version == decided_version
    conflict = await ProposalService(session, actor=user).partial_apply(
        project=project, proposal_id=proposal.id,
        apply_input=PartialApplyInput(decisions=[
            ProposalDecision(item_id=accept_item.id, decision="rejected"),
        ]),
    )
    assert conflict.failed and accept_item.status == "accepted"

    assert accept_item.status == "accepted"
    assert reject_item.status == "rejected"
    assert result.accepted == [accept_item.id]
    assert result.rejected == [reject_item.id]
    notices = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.topic == "production.facts.v1",
    ))).all()
    assert len(notices) == 1
    assert notices[0].payload["notice"] == {
        "kind": "proposal_decided", "proposal_id": str(proposal.id),
    }


@pytest.mark.asyncio
async def test_proposal_rejection_blocks_immediately_and_notifies_turn_independently(session):
    from app.director.inbox import receive_production_event
    from app.director.turn_models import DirectorTurn
    from app.director.turn_service import DirectorTurnService
    from app.director.wakeup import apply_director_wakeup
    from app.shared.errors import ConflictError, ValidationAppError

    project, shot, user = await _seed(session)
    proposal = DirectorProposal(project_id=project.id, thread_id=uuid4(), scope_type="shot",
                                scope_entity_id=shot.id, created_by=user.id, status="pending")
    session.add(proposal)
    await session.flush()
    item = DirectorProposalItem(proposal_id=proposal.id, project_id=project.id,
                                command="shot.update_video_prompt",
                                payload={"shot_id": str(shot.id), "video_prompt": "not accepted"},
                                expected_target_version=shot.version, status="pending")
    turn = DirectorTurn(project_id=project.id, workspace_id=project.workspace_id, actor_id=user.id,
                        scope_type="shot", scope_entity_id=shot.id, request_key="proposal:reject",
                        context_hash="f" * 64, status="awaiting_user", proposal_id=proposal.id,
                        step_count=1, request_summary={"max_steps": 4})
    session.add_all([item, turn])
    await session.flush()
    service = ProposalService(session, actor=user)
    await service.partial_apply(
        project=project, proposal_id=proposal.id,
        apply_input=PartialApplyInput(decisions=[
            ProposalDecision(item_id=item.id, decision="rejected"),
        ]),
    )
    assert turn.status == "awaiting_user"
    await session.commit()
    with pytest.raises(ConflictError) as rejected:
        await DirectorTurnService(session).assert_context_not_rejected(
            project_id=project.id, context_hash=turn.context_hash,
        )
    assert rejected.value.details["code"] == "DIRECTOR_CONTEXT_REJECTED"
    notice = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.topic == "production.facts.v1",
    ))).one()
    inbox_id = await receive_production_event(
        session, project_id=project.id, event_id=notice.event_id,
    )
    await session.commit()
    assert await apply_director_wakeup(session, inbox_id=inbox_id)
    await session.commit()
    await session.refresh(turn)
    assert turn.status == "completed" and turn.wait_reason == "proposal_rejected"
    with pytest.raises(ValidationAppError) as duplicate:
        await service.partial_apply(project=project, proposal_id=proposal.id,
            apply_input=PartialApplyInput(decisions=[
                ProposalDecision(item_id=item.id, decision="accepted"),
                ProposalDecision(item_id=item.id, decision="rejected"),
            ]))
    assert duplicate.value.details["code"] == "PROPOSAL_DUPLICATE_DECISION"
    assert shot.video_prompt == "video" and shot.version == 1
