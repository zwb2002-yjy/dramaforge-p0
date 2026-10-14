"""Creation-only persistence invariants shared by Director feature callers."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.config import Settings
from app.contracts.production_commands import ExecutionBody
from app.director.assistant_models import DirectorThread
from app.director.proposal_creation import ProposalItemDraft, create_proposal
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.runtime import delegation
from app.shared.base import Base
from sqlalchemy import func, select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def creation_context() -> AsyncIterator[tuple[AsyncSession, DirectorThread, Project, User]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            actor = User(
                email="creator@example.com", display_name="Creator", password_hash="unused",
            )
            session.add(actor)
            await session.flush()
            workspace = Workspace(owner_user_id=actor.id, name="Creation")
            session.add(workspace)
            await session.flush()
            project = Project(
                workspace_id=workspace.id, name="Creation", aspect_ratio="16:9", budget_limit=0,
            )
            session.add(project)
            await session.flush()
            thread = DirectorThread(
                project_id=project.id, scope_type="project", scope_entity_id=project.id,
                created_by=actor.id,
            )
            session.add(thread)
            await session.commit()
            yield session, thread, project, actor
    finally:
        await engine.dispose()


async def test_pending_creation_preserves_order_ownership_defaults_and_caller_transaction(
    creation_context, monkeypatch,
):
    session, thread, project, actor = creation_context
    commit = AsyncMock(wraps=session.commit)
    rollback = AsyncMock(wraps=session.rollback)
    monkeypatch.setattr(session, "commit", commit)
    monkeypatch.setattr(session, "rollback", rollback)
    target = uuid4()
    payload = {"sort_order": 7, "key": "first", "nested": {"value": 1}}
    proposal, items = await create_proposal(
        session, thread=thread, scope_type="edit_session", scope_entity_id=target,
        created_by=actor.id,
        items=[
            ProposalItemDraft(command="first", payload=payload, expected_target_version=4),
            ProposalItemDraft(
                command="second", payload={"sort_order": 2}, rationale="why", benefit="gain",
                cost="cost", risk="risk", impact="impact",
            ),
        ],
    )
    assert proposal.id is not None
    assert proposal.thread_id == thread.id
    assert proposal.project_id == project.id
    assert proposal.created_by == actor.id
    assert proposal.scope_type == "edit_session" and proposal.scope_entity_id == target
    assert proposal.status == "pending" and proposal.decided_at is None
    assert [item.command for item in items] == ["first", "second"]
    assert [item.expected_target_version for item in items] == [4, None]
    assert [item.payload["sort_order"] for item in items] == [7, 2]
    assert items[0].payload == payload and items[0].payload is not payload
    assert (items[0].rationale, items[0].benefit, items[0].cost,
            items[0].risk, items[0].impact) == ("", "", "", "", "")
    assert (items[1].rationale, items[1].benefit, items[1].cost,
            items[1].risk, items[1].impact) == ("why", "gain", "cost", "risk", "impact")
    ids = [item.id for item in items]
    assert len(set(ids)) == 2 and all(ids)
    for item in items:
        assert item.proposal_id == proposal.id and item.project_id == project.id
        assert item.status == "pending" and item.decided_at is None
    session.expunge_all()
    reloaded = await session.get(DirectorProposalItem, ids[0])
    assert reloaded is not None and reloaded.payload == payload
    assert await session.scalar(select(func.count(DirectorProposal.id))) == 1
    commit.assert_not_awaited()
    rollback.assert_not_awaited()
    await session.rollback()
    assert await session.scalar(select(func.count(DirectorProposal.id))) == 0
    assert await session.scalar(select(func.count(DirectorProposalItem.id))) == 0


async def test_failed_item_flush_leaves_rollback_to_caller(creation_context, monkeypatch):
    session, thread, project, actor = creation_context
    commit = AsyncMock(wraps=session.commit)
    rollback = AsyncMock(wraps=session.rollback)
    monkeypatch.setattr(session, "commit", commit)
    monkeypatch.setattr(session, "rollback", rollback)
    with pytest.raises(StatementError):
        await create_proposal(
            session, thread=thread, scope_type="project", scope_entity_id=project.id,
            created_by=actor.id,
            items=[ProposalItemDraft(command="invalid-json", payload={"value": object()})],
        )
    commit.assert_not_awaited()
    rollback.assert_not_awaited()
    await session.rollback()
    assert await session.scalar(select(func.count(DirectorProposal.id))) == 0
    assert await session.scalar(select(func.count(DirectorProposalItem.id))) == 0


async def test_delegation_records_existing_user_grant_without_changing_execution_payload(
    creation_context, monkeypatch,
):
    session, _thread, project, actor = creation_context
    shot_id, decision_id, authorization_id = uuid4(), uuid4(), uuid4()
    execution = ExecutionBody(
        stage="video", prompt="test", mode_id="test-mode", expected_shot_version=7,
        plan_fingerprint="a" * 64,
    )
    approve = AsyncMock(return_value=authorization_id)
    build_plan = AsyncMock(return_value=SimpleNamespace(
        plan_fingerprint=execution.plan_fingerprint, accepted_approximations=[],
    ))
    receipt = (object(), object())
    start = AsyncMock(return_value=receipt)
    monkeypatch.setattr(delegation.ProductionAuthorizations, "approve_user_action", approve)
    monkeypatch.setattr(delegation.WorkbenchExecutionService, "build_plan", build_plan)
    monkeypatch.setattr(delegation.DirectorRuntimeStartService, "accept", start)
    commit = AsyncMock(wraps=session.commit)
    monkeypatch.setattr(session, "commit", commit)
    before = datetime.now(UTC)
    result = await delegation.DirectorRuntimeDelegationService(
        session, settings=Settings(director_runtime_engine="langgraph"),
    ).accept(
        project=project, actor=actor, shot_id=shot_id, decision_id=decision_id,
        execution=execution, authorization_expires_at=before + timedelta(minutes=10), max_steps=1,
    )
    assert result is receipt
    approve.assert_awaited_once()
    proposal = (await session.scalars(select(DirectorProposal))).one()
    item = (await session.scalars(select(DirectorProposalItem))).one()
    assert proposal.status == "applied" and item.status == "accepted"
    assert proposal.decided_at == item.decided_at
    assert proposal.decided_at.replace(tzinfo=UTC) >= before
    assert proposal.scope_type == "shot" and proposal.scope_entity_id == shot_id
    assert proposal.created_by == actor.id
    assert proposal.project_id == item.project_id == project.id
    assert item.proposal_id == proposal.id
    assert item.command == "production.request_stage_execution"
    assert item.expected_target_version == 7
    assert item.payload == {
        "shot_id": str(shot_id), "stage": "video", "authorization_ref": str(authorization_id),
        "plan_fingerprint": execution.plan_fingerprint,
    }
    start.assert_awaited_once_with(
        project=project, actor=actor, proposal_id=proposal.id,
        authorization_ref=authorization_id, request_key=f"director-delegation:{decision_id}",
        max_steps=1,
    )
    commit.assert_not_awaited()
