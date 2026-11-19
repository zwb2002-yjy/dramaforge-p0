"""Pending runtime resume read model (I7)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.director.runtime.models import DirectorRuntimeControl, DirectorRuntimeWakeup
from app.director.turn_models import DirectorTurn
from app.shared.errors import NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_turn(session: AsyncSession) -> tuple[User, Project, DirectorTurn, str]:
    user = User(
        email=f"resume-{uuid4().hex}@example.com",
        display_name="R",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="W")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id, name="P", aspect_ratio="9:16", budget_limit=0
    )
    session.add(project)
    await session.flush()
    execution_id = uuid4()
    turn = DirectorTurn(
        workspace_id=workspace.id,
        project_id=project.id,
        actor_id=user.id,
        thread_id=None,
        turn_kind="workflow",
        scope_type="project",
        scope_entity_id=project.id,
        request_key=f"resume-{uuid4().hex}",
        context_hash="c" * 64,
        input_versions={},
        intent_snapshot={},
        model_resolution={},
        request_summary={},
        response_summary={},
        token_usage={},
        runtime_execution_id=execution_id,
        runtime_revision=3,
        engine_version="test-engine",
        state_schema_version="test-state",
        status="awaiting_execution",
        revision=1,
    )
    session.add(turn)
    await session.flush()
    session.add(
        DirectorRuntimeControl(
            runtime_execution_id=execution_id,
            project_id=project.id,
            turn_id=turn.id,
            engine_version="test",
            state_schema_version="test",
            status="waiting",
            revision=1,
        )
    )
    await session.flush()
    return user, project, turn, str(execution_id)


async def _read(project: Project, turn: DirectorTurn, user: User, session: AsyncSession):
    from app.api.v1.director import read_director_runtime_resume

    return await read_director_runtime_resume(
        project_id=project.id, turn_id=turn.id, user=user, session=session
    )


@pytest.mark.asyncio
async def test_resume_read_exposes_the_pending_signal(session: AsyncSession) -> None:
    user, project, turn, execution_id = await _seed_turn(session)
    signal_id = uuid4()
    reference_id = uuid4()
    session.add(
        DirectorRuntimeWakeup(
            project_id=project.id,
            runtime_execution_id=turn.runtime_execution_id,
            kind="resume",
            dedupe_key=f"resume:{execution_id}:{signal_id}",
            payload={
                "signal_id": str(signal_id),
                "reference_id": str(reference_id),
                "expected_revision": 3,
                "reason": "production_fact",
            },
            attempt_count=1,
        )
    )
    await session.flush()
    read = await _read(project, turn, user, session)
    assert read.signal_id == signal_id
    assert read.reference_id == reference_id
    assert read.expected_runtime_revision == 3
    assert read.attempt_count == 1


@pytest.mark.asyncio
async def test_resume_read_ignores_completed_wakeups(session: AsyncSession) -> None:
    user, project, turn, execution_id = await _seed_turn(session)
    session.add(
        DirectorRuntimeWakeup(
            project_id=project.id,
            runtime_execution_id=turn.runtime_execution_id,
            kind="resume",
            dedupe_key=f"resume:{execution_id}:{uuid4()}",
            payload={"signal_id": str(uuid4()), "reference_id": str(uuid4()), "expected_revision": 3},
            attempt_count=1,
            completed_at=datetime.now(UTC),
        )
    )
    await session.flush()
    with pytest.raises(NotFoundError) as missing:
        await _read(project, turn, user, session)
    assert missing.value.details["code"] == "DIRECTOR_RESUME_NOT_PENDING"
