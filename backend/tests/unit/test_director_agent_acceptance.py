"""Durable Agent acceptance, atomic adoption, fencing and restart recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.contracts.agent import AgentModelResponse
from app.director.agent_service import (
    ACCEPTED_EVENT_TOPIC,
    AgentRequest,
    AgentThreadCreate,
    recover_expired,
)
from app.director.assistant_models import DirectorMessage
from app.director.turn_models import DirectorTurn
from app.events.models import EventLog, OutboxEvent
from app.shared.errors import ConflictError
from sqlalchemy import func, select
from test_director_agent_service import (
    AgentWorld,
    ScriptedModel,
    accept_turn,
    execute,
    read_shot,
)
from test_director_agent_service import agent_world as agent_world


async def _turn(world: AgentWorld, turn_id: UUID) -> DirectorTurn:
    async with world.factory() as session:
        turn = await session.get(DirectorTurn, turn_id)
        assert turn is not None
        return turn


async def test_policy_changed_after_acceptance_blocks_agent_before_submission(agent_world):
    from app.access.models import Project, User
    from app.access.project_data_policy import ProjectDataPolicy
    from app.director.invocation_models import DirectorInvocation

    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel()
    receipt = await accept_turn(
        world, thread.id, AgentRequest(content="灯笼", request_key="local-only"), model=model
    )
    async with world.factory() as session:
        actor = await session.get(User, world.service.actor_id)
        project = await session.get(Project, world.service.project_id)
        await ProjectDataPolicy(session, actor=actor, project=project).put(
            expected_revision=0, mode="local_only",
            allowed_destination_revision_ids=[], allowed_purposes=[],
        )
        await session.commit()
    result = await execute(world, receipt, model=model)
    assert result.stop_reason == "EGRESS_LOCAL_ONLY" and not model.calls
    async with world.factory() as session:
        assert await session.scalar(select(func.count(DirectorInvocation.id))) == 0


async def test_acceptance_persists_queued_turn_message_and_outbox_without_model_call(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(AgentModelResponse(text="Never called during acceptance."))

    acceptance, created = await world.service.accept(
        thread.id,
        AgentRequest(content="Read my shot", request_key="accept-once"),
        model=model,
    )

    assert created is True
    assert acceptance.status == "queued"
    assert acceptance.accepted_revision == 1
    assert acceptance.request_key == "accept-once"
    assert acceptance.master_run_id is None
    assert acceptance.read_url.endswith("/requests?request_key=accept-once")
    assert model.calls == []
    turn = await _turn(world, acceptance.turn_id)
    assert turn.status == "queued" and turn.turn_kind == "agent"
    assert turn.agent_control_epoch == 0 and turn.agent_lease_token is None
    assert turn.request_summary["accepted_revision"] == 1
    assert turn.request_summary["request"]["content"] == "Read my shot"
    async with world.factory() as session:
        message = await session.get(DirectorMessage, acceptance.user_message_id)
        assert message is not None
        assert message.turn_id == acceptance.turn_id
        assert message.ordinal == 0 and message.role == "user"
        assert message.content == "Read my shot"
        events = list(await session.scalars(select(EventLog)))
        outbox = list(await session.scalars(select(OutboxEvent)))
        assert len(events) == 1 and len(outbox) == 1
        assert outbox[0].topic == ACCEPTED_EVENT_TOPIC
        assert outbox[0].payload["turn_id"] == str(acceptance.turn_id)
        assert outbox[0].payload["user_message_id"] == str(acceptance.user_message_id)


async def test_acceptance_replay_returns_the_original_fact_without_new_rows(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    request = AgentRequest(content="Hello", request_key="replay-once")
    first, created = await world.service.accept(thread.id, request, model=ScriptedModel())
    assert created is True

    replay, replayed = await world.service.accept(thread.id, request, model=ScriptedModel())

    assert replayed is False
    assert replay == first
    async with world.factory() as session:
        assert await session.scalar(select(func.count(DirectorTurn.id))) == 1
        assert await session.scalar(select(func.count(DirectorMessage.id))) == 1
        assert await session.scalar(select(func.count(OutboxEvent.id))) == 1
    with pytest.raises(ConflictError) as conflict:
        await world.service.accept(
            thread.id,
            AgentRequest(content="Different content", request_key="replay-once"),
            model=ScriptedModel(),
        )
    assert conflict.value.details["code"] == "AGENT_REQUEST_KEY_REUSED"


async def test_atomic_adoption_runs_once_and_a_second_worker_never_executes(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    acceptance = await accept_turn(
        world,
        thread.id,
        AgentRequest(content="Read shot", request_key="adopt-once"),
        model=ScriptedModel(),
    )
    model = ScriptedModel(AgentModelResponse(text="Adopted once."))

    first = await execute(world, acceptance, model=model)
    second = await execute(world, acceptance, model=model)

    assert first.status == "completed" and first.model_calls == 1
    assert second == first
    assert len(model.calls) == 1
    turn = await _turn(world, acceptance.turn_id)
    assert turn.agent_control_epoch == 2  # claim + finish
    assert turn.agent_lease_token is None


async def test_late_owner_result_cannot_overwrite_a_newer_epoch(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    acceptance = await accept_turn(
        world,
        thread.id,
        AgentRequest(content="Read shot", request_key="fenced-late"),
        model=ScriptedModel(),
    )
    observed: dict[str, object] = {}

    class ExpiringModel(ScriptedModel):
        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            async with world.factory() as session:
                turn = await session.get(DirectorTurn, kwargs["turn_id"])
                assert turn is not None and turn.status == "thinking"
                assert turn.agent_lease_token is not None
                observed["epoch"] = turn.agent_control_epoch
                # The worker stalls until its lease expires; recovery fences it.
                turn.agent_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()
            async with world.factory() as session:
                expired = await session.get(DirectorTurn, kwargs["turn_id"])
                assert expired is not None
                await recover_expired(session, project_id=world.service.project_id, turn=expired)
                await session.commit()
            return AgentModelResponse(text="A late answer from the replaced owner.")

    model = ExpiringModel()
    result = await execute(world, acceptance, model=model)

    assert result.status == "failed"
    assert result.stop_reason == "unknown_submission"
    assert result.assistant_message_id is None
    assert len(model.calls) == 1
    turn = await _turn(world, acceptance.turn_id)
    assert observed["epoch"] == 1
    assert turn.agent_control_epoch == 2
    assert turn.agent_lease_token is None
    async with world.factory() as session:
        assert (
            await session.scalar(
                select(func.count(DirectorMessage.id)).where(
                    DirectorMessage.turn_id == acceptance.turn_id,
                    DirectorMessage.role == "assistant",
                )
            )
            == 0
        )
    # A later worker never adopts the fenced Turn or repeats the submission.
    assert await execute(world, acceptance, model=model) == result
    assert len(model.calls) == 1


async def test_unknown_submission_is_never_resent_by_any_later_worker(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    acceptance = await accept_turn(
        world,
        thread.id,
        AgentRequest(content="Analyze", request_key="unknown-never"),
        model=ScriptedModel(),
    )
    model = ScriptedModel(TimeoutError("possibly billed"))

    first = await execute(world, acceptance, model=model)
    again = await execute(world, acceptance, model=model)

    assert first.status == "failed" and first.stop_reason == "unknown_submission"
    assert again == first
    assert len(model.calls) == 1
    turn = await _turn(world, acceptance.turn_id)
    assert turn.transport_status == "unknown_submission"


async def test_expired_queue_wait_fails_without_execution(agent_world: AgentWorld) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    acceptance = await accept_turn(
        world,
        thread.id,
        AgentRequest(content="Read shot", request_key="deadline-passed"),
        model=ScriptedModel(),
    )
    async with world.factory() as session:
        turn = await session.get(DirectorTurn, acceptance.turn_id)
        assert turn is not None
        turn.deadline = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    model = ScriptedModel(AgentModelResponse(text="Must not run."))

    result = await execute(world, acceptance, model=model)

    assert result.status == "failed" and result.stop_reason == "deadline_exceeded"
    assert model.calls == []
    saved = await _turn(world, acceptance.turn_id)
    assert saved.status == "failed" and saved.agent_lease_token is None


async def test_worker_scan_finds_queued_work_without_any_published_wakeup(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    acceptance = await accept_turn(
        world,
        thread.id,
        AgentRequest(content="Read shot", request_key="scan-only"),
        model=ScriptedModel(),
    )
    # Simulate a lost Outbox publish/Redis job: only the database fact remains.
    async with world.factory() as session:
        event = await session.scalar(select(OutboxEvent))
        assert event is not None and event.status == "pending"
        await session.delete(event)
        await session.commit()
    from app.shared.db import list_pending_agent_turn_rls_scopes

    async with world.factory() as session:
        found = await list_pending_agent_turn_rls_scopes(session, limit=10)
    assert [turn_id for turn_id, _scope in found] == [acceptance.turn_id]

    model = ScriptedModel(AgentModelResponse(text="Executed from the durable scan."))
    result = await execute(world, acceptance, model=model)
    assert result.status == "completed" and len(model.calls) == 1
    async with world.factory() as session:
        assert await list_pending_agent_turn_rls_scopes(session, limit=10) == []


async def test_acceptance_keeps_the_frozen_tool_contract_for_later_execution(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(read_shot(world.shot_id), AgentModelResponse(text="Read complete."))
    acceptance = await accept_turn(
        world,
        thread.id,
        AgentRequest(content="Read my shot", request_key="frozen-tools"),
        model=model,
    )
    turn = await _turn(world, acceptance.turn_id)
    frozen = turn.intent_snapshot["tools"]
    assert isinstance(frozen, list) and frozen

    result = await execute(world, acceptance, model=model)

    assert result.status == "completed"
    saved = await _turn(world, acceptance.turn_id)
    assert saved.intent_snapshot["tools"] == frozen
    assert saved.context_hash == turn.context_hash


async def test_selected_candidate_is_bound_to_messages_and_replay(agent_world: AgentWorld) -> None:
    from app.director.agent_service import AgentUIContext, SelectedReference
    from app.execution.models import Artifact
    from app.shared.errors import NotFoundError

    w = agent_world
    thread = await w.service.open_thread(AgentThreadCreate())
    async with w.factory() as session:
        media = Artifact(
            project_id=w.service.project_id,
            artifact_type="image",
            storage_state="available",
            object_key="fixture/private",
            content_hash="f" * 64,
            mime_type="image/png",
            byte_size=100,
        )
        other = Artifact(
            project_id=w.other_project_id,
            artifact_type="image",
            storage_state="available",
            object_key="fixture/foreign",
            content_hash="e" * 64,
            mime_type="image/png",
            byte_size=100,
        )
        session.add_all([media, other])
        await session.commit()
    context = AgentUIContext(
        selected_refs=[
            SelectedReference(kind="artifact", id=media.id),
        ]
    )
    request = AgentRequest(content="讨论这个候选", request_key="selection", ui_context=context)
    model = ScriptedModel(AgentModelResponse(text="已记录候选。"))
    with pytest.raises(NotFoundError):
        await w.service.accept(
            thread.id,
            request.model_copy(
                update={
                    "ui_context": AgentUIContext(
                        selected_refs=[SelectedReference(kind="artifact", id=other.id)]
                    )
                }
            ),
            model=model,
        )
    with pytest.raises(NotFoundError):
        await w.service.accept(
            thread.id,
            request.model_copy(
                update={
                    "ui_context": AgentUIContext(
                        selected_refs=[
                            SelectedReference(kind="shot", id=w.shot_id),
                            SelectedReference(kind="artifact", id=media.id),
                        ]
                    )
                }
            ),
            model=model,
        )
    from app.execution.models import NodeRun
    from app.production.service import GraphService

    async with w.factory() as session:
        gs = GraphService(session)
        graph = await gs.create_graph(
            project_id=w.service.project_id,
            scope_type="shot",
            scope_entity_id=w.shot_id,
            template_key="ui-selection-test",
            created_by=w.service.actor_id,
            definition={
                "nodes": [{"key": "keyframe", "type": "keyframe", "name": "Frame"}],
                "edges": [],
            },
        )
        materialized = await gs.materialize_definition(version_id=graph.current_version_id)
        producer = NodeRun(
            project_id=w.service.project_id,
            graph_version_id=materialized.version.id,
            graph_node_id=materialized.nodes["keyframe"].id,
            attempt_no=1,
            idempotency_key="ui-candidate",
            input_hash="d" * 64,
            status="completed",
            result_artifact_id=media.id,
            created_by=w.service.actor_id,
            input_snapshot={"shot_id": str(w.shot_id)},
        )
        session.add(producer)
        await session.flush()
        stored = await session.get(Artifact, media.id)
        stored.produced_by_run_id = producer.id
        await session.commit()
    context.selected_refs.insert(0, SelectedReference(kind="shot", id=w.shot_id))
    accepted = await accept_turn(w, thread.id, request, model=model)
    assert not model.calls
    assert (await _turn(w, accepted.turn_id)).intent_snapshot["ui_context"] == context.model_dump(
        mode="json"
    )
    await execute(w, accepted, model=model)
    assert len(model.calls) == 1
    assert str(media.id) in str(model.calls[0]["messages"])
    assert "fixture/private" not in str(model.calls[0]["messages"])
    page = await w.service.read_thread(thread.id, limit=20, offset=None)
    messages = [row for row in page["messages"] if row["turn_id"] == accepted.turn_id]
    assert {row["role"] for row in messages} == {"user", "assistant"}
    assert all(row["context"] == context.model_dump(mode="json") for row in messages)
    with pytest.raises(ConflictError):
        await w.service.replay(thread.id, request.model_copy(update={"ui_context": None}))
