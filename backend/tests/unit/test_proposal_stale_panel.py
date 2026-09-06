"""P7-08/09 + Phase 7 Gate tests (03 §68/§69/§70)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.proposal_service import PartialApplyInput, ProposalDecision, ProposalService
from app.production.models import ShotExperiment, ShotReferenceBinding
from app.shared.base import Base
from app.shared.security import hash_password
from sqlalchemy import select
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
        email=f"gate7-{uuid4().hex}@example.com",
        display_name="Gate7",
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


async def _proposal_with_items(
    session: AsyncSession,
    *,
    project: Project,
    shot: Shot,
    user: User,
) -> tuple[DirectorProposal, dict[str, DirectorProposalItem]]:
    proposal = DirectorProposal(
        project_id=project.id, thread_id=uuid4(), scope_type="shot",
        scope_entity_id=shot.id, status="pending", created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    low_camera = DirectorProposalItem(
        proposal_id=proposal.id, project_id=project.id,
        command="shot.update_director_state",
        payload={"shot_id": str(shot.id), "director_state": {"camera": "low"}},
        expected_target_version=shot.version, status="pending",
    )
    model_swap = DirectorProposalItem(
        proposal_id=proposal.id, project_id=project.id,
        command="shot.set_model_override",
        payload={"shot_id": str(shot.id), "model_overrides": {"video.shot": "model-x"}},
        expected_target_version=shot.version, status="pending",
    )
    add_ref = DirectorProposalItem(
        proposal_id=proposal.id, project_id=project.id,
        command="shot_reference.add",
        payload={"shot_id": str(shot.id), "purpose": "identity", "asset_id": str(uuid4())},
        expected_target_version=shot.version, status="pending",
    )
    session.add_all([low_camera, model_swap, add_ref])
    await session.flush()
    return proposal, {"camera": low_camera, "model": model_swap, "ref": add_ref}


@pytest.mark.asyncio
async def test_phase7_gate_accept_two_reject_one(session: AsyncSession) -> None:
    """§70: accept low camera + add reference, reject model swap -> only two
    changes, model unchanged, shot version correct."""
    project, shot, user = await _seed(session)
    proposal, items = await _proposal_with_items(session, project=project, shot=shot, user=user)

    result = await ProposalService(session, actor=user).partial_apply(
        project=project,
        proposal_id=proposal.id,
        apply_input=PartialApplyInput(
            decisions=[
                ProposalDecision(item_id=items["camera"].id, decision="accepted"),
                ProposalDecision(item_id=items["ref"].id, decision="accepted"),
                ProposalDecision(item_id=items["model"].id, decision="rejected"),
            ]
        ),
    )
    await session.refresh(shot)
    # low camera applied
    assert shot.director_state == {"camera": "low"}
    # reference added
    refs = (
        await session.execute(
            select(ShotReferenceBinding).where(ShotReferenceBinding.shot_id == shot.id)
        )
    ).scalars().all()
    assert len(refs) == 1
    assert refs[0].purpose == "identity"
    # model swap rejected -> no ShotExperiment created, model unchanged
    experiments = (
        await session.execute(
            select(ShotExperiment).where(ShotExperiment.shot_id == shot.id)
        )
    ).scalars().all()
    assert experiments == []
    # only ONE shot version bump (from the accepted director_state command)
    assert shot.version == 2
    assert set(result.accepted) == {items["camera"].id, items["ref"].id}
    assert result.rejected == [items["model"].id]


@pytest.mark.asyncio
async def test_phase7_gate_manual_edit_makes_old_proposal_stale(session: AsyncSession) -> None:
    """§70: user manually edits the shot -> old suggestion becomes stale."""
    project, shot, user = await _seed(session)
    proposal, items = await _proposal_with_items(session, project=project, shot=shot, user=user)

    # user manually edits the shot (v1 -> v2)
    shot.version = 2
    await session.flush()

    service = ProposalService(session, actor=user)
    marked = await service.mark_proposals_stale_for_shot(
        project_id=project.id, shot_id=shot.id, current_version=shot.version
    )
    assert marked == 3
    # old accepted attempt is recorded as failed (stale), never applied
    result = await service.partial_apply(
        project=project,
        proposal_id=proposal.id,
        apply_input=PartialApplyInput(
            decisions=[ProposalDecision(item_id=items["camera"].id, decision="accepted")]
        ),
    )
    assert result.failed and "stale" in result.failed[0]["error"]
    await session.refresh(shot)
    assert shot.director_state == {"camera": "static"}  # not applied
    await session.refresh(items["camera"])
    assert items["camera"].status == "stale"


@pytest.mark.asyncio
async def test_panel_close_semantics_unconfirmed_not_executed(session: AsyncSession) -> None:
    """§69: an unconfirmed proposal is never executed; closing the panel does
    not cancel queued runs (runs stay queued/independent)."""
    project, shot, user = await _seed(session)
    proposal, items = await _proposal_with_items(session, project=project, shot=shot, user=user)
    # no decisions given -> nothing applied
    await session.refresh(shot)
    assert shot.director_state == {"camera": "static"}
    assert shot.version == 1
    # proposal remains pending (not executed)
    await session.refresh(proposal)
    assert proposal.status == "pending"
    await session.refresh(items["camera"])
    assert items["camera"].status == "pending"
