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
from app.shared.base import Base
from app.shared.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
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
async def test_partial_apply_only_executes_accepted(session: AsyncSession) -> None:
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
    assert accept_item.status == "accepted"
    assert reject_item.status == "rejected"
    assert result.accepted == [accept_item.id]
    assert result.rejected == [reject_item.id]
