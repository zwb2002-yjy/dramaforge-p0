"""Real DB history selection preserves complete turns and makes omissions explicit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.contracts.agent import AgentMessage
from app.director.agent_context import fit_agent_context
from app.director.agent_history import AgentHistoryInvalid, load_agent_history
from app.director.agent_service import AgentThreadCreate
from app.director.assistant_models import DirectorMessage
from app.director.turn_models import DirectorTurn
from app.shared.errors import NotFoundError
from sqlalchemy import select
from tests.unit.test_director_agent_service import AgentWorld
from tests.unit.test_director_agent_service import agent_world as agent_world

AT = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)


async def _turn(
    world: AgentWorld,
    thread_id: UUID,
    number: int,
    *,
    status: str = "completed",
    kind: str = "agent",
    content: str = "",
    complete: bool = True,
    extra_assistant: bool = False,
) -> UUID:
    identity = UUID(int=1000 + number)
    async with world.factory() as session:
        session.add(
            DirectorTurn(
                id=identity,
                project_id=world.service.project_id,
                workspace_id=world.service.workspace_id,
                actor_id=world.service.actor_id,
                thread_id=thread_id,
                turn_kind=kind,
                scope_type="project",
                scope_entity_id=world.service.project_id,
                request_key=f"history-{number}",
                context_hash="a" * 64,
                status=status,
                created_at=AT,
            )
        )
        await session.flush()
        for ordinal, role in enumerate(["user", *(["assistant"] if complete else [])]):
            session.add(
                DirectorMessage(
                    project_id=world.service.project_id,
                    thread_id=thread_id,
                    turn_id=identity,
                    ordinal=ordinal,
                    role=role,
                    content=content or f"{role}-{number}",
                    # Deliberately disagree with ordinal: order must not come from timestamps.
                    created_at=AT + timedelta(seconds=1 - ordinal),
                )
            )
        if extra_assistant:
            session.add(
                DirectorMessage(
                    project_id=world.service.project_id,
                    thread_id=thread_id,
                    turn_id=identity,
                    ordinal=2,
                    role="assistant",
                    content=f"extra-{number}",
                    created_at=AT,
                )
            )
        await session.commit()
    return identity


async def test_selects_latest_complete_turn_groups_with_stable_ties_and_ordinals(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    ids = [
        await _turn(world, thread.id, number, extra_assistant=number == 4) for number in range(6)
    ]
    for number, status in enumerate(("failed", "cancelled", "thinking", "stale"), start=90):
        await _turn(world, thread.id, number, status=status)
    await _turn(world, thread.id, 94, kind="workflow")
    await _turn(world, thread.id, 95, complete=False)
    async with world.factory() as session:
        first = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=thread.id, max_turn_groups=2
        )
        second = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=thread.id, max_turn_groups=2
        )
    assert first.selected_turn_ids == tuple(ids[-2:])
    assert first.total_completed_groups == 6 and first.window_omitted_groups == 4
    assert [message.content for message in first.messages] == [
        "user-4",
        "assistant-4",
        "extra-4",
        "user-5",
        "assistant-5",
    ]
    assert first.audit["excluded_incomplete_turns"] == 1
    assert first.source_range_hash == second.source_range_hash
    assert first.history_notice is not None
    notice = json.loads(first.history_notice.content)["history_window"]
    assert notice["omitted_completed_groups"] == 4
    assert notice["excluded_incomplete_turns"] == 1
    assert "assistant-4" not in json.dumps(first.audit)


async def test_query_window_omissions_are_separate_from_byte_budget_omissions(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    for number in range(6):
        await _turn(world, thread.id, number, content="complete historical evidence; " * 300)
    async with world.factory() as session:
        history = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=thread.id, max_turn_groups=2
        )
    assert history.history_notice is not None
    current = AgentMessage(role="user", content="Only current scope is authoritative.")
    projection = fit_agent_context(
        messages=[
            AgentMessage(role="system", content="Safety and frozen scope"),
            history.history_notice,
            *history.messages,
            current,
        ],
        tools=[],
        max_bytes=4096,
    )
    assert history.window_omitted_groups == 4
    assert projection.omitted_history_groups == 2
    assert projection.messages[-1] == current
    assert (
        json.loads(projection.messages[1].content)["history_window"]["omitted_completed_groups"]
        == 4
    )


async def test_legacy_messages_are_explicit_advisory_not_invented_completed_turns(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    texts = [
        "orphan legacy assistant",
        "legacy question " * 200,
        "legacy answer; keep final marker",
    ]
    async with world.factory() as session:
        for index, content in enumerate(texts):
            session.add(
                DirectorMessage(
                    id=UUID(int=2000 + index),
                    project_id=world.service.project_id,
                    thread_id=thread.id,
                    role="user" if index == 1 else "assistant",
                    content=content,
                    created_at=AT,
                )
            )
        await session.commit()
        excluded = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=thread.id
        )
        included = await load_agent_history(
            session,
            project_id=world.service.project_id,
            thread_id=thread.id,
            legacy_message_limit=2,
        )
    assert excluded.messages == included.messages == ()
    assert excluded.total_completed_groups == included.total_completed_groups == 0
    assert excluded.window_omitted_groups == included.window_omitted_groups == 0
    assert excluded.legacy_advisory is None and excluded.legacy_omitted_messages == 3
    assert included.legacy_message_count == 2 and included.legacy_omitted_messages == 1
    assert included.legacy_advisory is not None
    data = json.loads(included.legacy_advisory.content)["legacy_history_advisory"]
    assert data["complete_turns"] is False
    assert [row["content"] for row in data["messages"]] == texts[-2:]
    assert excluded.source_range_hash != included.source_range_hash


async def test_scope_is_rechecked_and_other_threads_are_not_included(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    project_thread = await world.service.open_thread(AgentThreadCreate())
    shot_thread = await world.service.open_thread(
        AgentThreadCreate(scope_type="shot", scope_entity_id=world.shot_id)
    )
    await _turn(world, project_thread.id, 1)
    await _turn(world, shot_thread.id, 2)
    async with world.factory() as session:
        history = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=project_thread.id
        )
        assert [message.content for message in history.messages] == ["user-1", "assistant-1"]
        for project_id, thread_id in (
            (world.other_project_id, project_thread.id),
            (world.service.project_id, uuid4()),
        ):
            with pytest.raises(NotFoundError):
                await load_agent_history(session, project_id=project_id, thread_id=thread_id)


async def test_source_hash_covers_selected_revision_and_content(agent_world: AgentWorld) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    identity = await _turn(world, thread.id, 1)
    async with world.factory() as session:
        before = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=thread.id
        )
        turn = await session.get(DirectorTurn, identity)
        assert turn is not None
        turn.revision += 1
        await session.commit()
        changed = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=thread.id
        )
        message = await session.scalar(
            select(DirectorMessage).where(
                DirectorMessage.turn_id == identity,
                DirectorMessage.ordinal == 1,
            )
        )
        assert message is not None
        message.content = "A corrected stored answer"
        await session.commit()
        corrected = await load_agent_history(
            session, project_id=world.service.project_id, thread_id=thread.id
        )
    assert changed.source_range_hash != before.source_range_hash
    assert corrected.source_range_hash != changed.source_range_hash


@pytest.mark.parametrize("invalid", ["gap", "role", "blank"])
async def test_malformed_completed_transcript_is_not_silently_repaired(
    agent_world: AgentWorld,
    invalid: str,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    identity = await _turn(world, thread.id, 1)
    async with world.factory() as session:
        session.add(
            DirectorMessage(
                project_id=world.service.project_id,
                thread_id=thread.id,
                turn_id=identity,
                ordinal=3 if invalid == "gap" else 2,
                role="user" if invalid == "role" else "assistant",
                content=" " if invalid == "blank" else "extra",
            )
        )
        await session.commit()
        with pytest.raises(AgentHistoryInvalid):
            await load_agent_history(
                session, project_id=world.service.project_id, thread_id=thread.id
            )


@pytest.mark.parametrize("limit", [-1, 21, True])
async def test_history_window_bound_is_validated(agent_world: AgentWorld, limit) -> None:
    async with agent_world.factory() as session:
        with pytest.raises(AgentHistoryInvalid):
            await load_agent_history(
                session,
                project_id=agent_world.service.project_id,
                thread_id=uuid4(),
                max_turn_groups=limit,
            )
