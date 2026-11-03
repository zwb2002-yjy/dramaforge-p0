"""A same-key shot change proposal serializes on the Project row before insert.

The endpoint used to read the idempotency key and insert in the same window, so a
concurrent retry hit ``uq_shot_change_proposal_idempotency`` and surfaced as a
bare 500.  The Project row lock now makes the read-and-insert window atomic.
"""

import asyncio
from uuid import uuid4

import pytest
from app.api.v1.scripts import ShotChangeProposalCreate, create_shot_change_proposal
from app.assets.models import ShotChangeProposal
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark
from tests.unit.test_review_gate import _env


@pytest.mark.asyncio
async def test_same_key_change_proposal_waits_for_the_project_lock_pg(pg_session) -> None:
    user, project, shot = await _env(pg_session)
    project_id, shot_id, user_id, version = project.id, shot.id, user.id, shot.version
    key = f"change-{uuid4()}"
    await pg_session.commit()

    # A concurrent request wins the key while this one is still inside the
    # read-and-insert window: it holds the Project row lock, inserts, commits.
    await pg_session.execute(
        text("SELECT id FROM projects WHERE id = :project_id FOR UPDATE"),
        {"project_id": project_id},
    )
    holder_pid = await pg_session.scalar(text("SELECT pg_backend_pid()"))
    factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
    pids: dict[str, int] = {}
    outcome: dict[str, object] = {}
    started = asyncio.Event()

    async def create() -> None:
        async with factory() as session:
            pids["create"] = await session.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            session.info["selected_workspace_id"] = project.workspace_id
            actor = await session.get(type(user), user_id)
            outcome["result"] = await create_shot_change_proposal(
                project_id,
                shot_id,
                ShotChangeProposalCreate(
                    idempotency_key=key,
                    summary="concurrent retry",
                    expected_version=version,
                    replacement_payload={"visual_description": "locked lead"},
                ),
                actor,
                session,
                None,
            )

    task = asyncio.create_task(create())
    try:
        await asyncio.wait_for(started.wait(), timeout=10)

        async def wait_for_lock() -> None:
            while True:
                if task.done():
                    await task
                    raise AssertionError("create never waited for the Project lock")
                blockers = await pg_session.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["create"]}
                )
                if holder_pid in blockers:
                    return
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_lock(), timeout=10)
        winner = ShotChangeProposal(
            project_id=project_id,
            shot_id=shot_id,
            created_by=user_id,
            idempotency_key=key,
            summary="first writer",
            base_shot_version=version,
            replacement_payload={"visual_description": "first"},
            affected_node_keys=[],
            reusable_artifact_ids=[],
        )
        pg_session.add(winner)
        await pg_session.commit()
        await asyncio.wait_for(task, timeout=10)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    result = outcome["result"]
    assert result.proposal.id == winner.id
    assert result.proposal.summary == "first writer"
    count = await pg_session.scalar(
        select(func.count())
        .select_from(ShotChangeProposal)
        .where(ShotChangeProposal.project_id == project_id)
    )
    assert count == 1
