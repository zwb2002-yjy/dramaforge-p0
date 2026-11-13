"""Agent service integration with real domain reads and fake text transport."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.contracts.agent import AgentModelResponse, AgentToolCall
from app.director import text_transport
from app.director.agent_service import AgentRequest, AgentThreadCreate, DirectorAgentService
from app.director.assistant_models import DirectorMessage, DirectorToolCall
from app.director.invocation_models import DirectorInvocation
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.execution.models import NodeRun, ProviderOperation
from app.shared.base import Base
from app.shared.errors import ConflictError, NotFoundError
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class ScriptedModel:
    resolution = {"model_id": "frozen-fake-model", "connection_revision": "r1"}

    def __init__(self, *responses: AgentModelResponse | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected extra model submission")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@dataclass
class AgentWorld:
    service: DirectorAgentService
    factory: async_sessionmaker[AsyncSession]
    shot_id: UUID
    other_project_id: UUID


@pytest.fixture
async def agent_world() -> AsyncIterator[AgentWorld]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        actor = User(
            email=f"service-{uuid4()}@example.com",
            display_name="Owner",
            password_hash="not-a-live-credential",
        )
        session.add(actor)
        await session.flush()
        workspace = Workspace(owner_user_id=actor.id, name="Culture")
        session.add(workspace)
        await session.flush()
        project = Project(
            workspace_id=workspace.id, name="Old bridge", aspect_ratio="16:9", budget_limit=0
        )
        other = Project(
            workspace_id=workspace.id, name="Other work", aspect_ratio="16:9", budget_limit=0
        )
        session.add_all([project, other])
        await session.flush()
        episode = Episode(project_id=project.id, episode_number=1)
        session.add(episode)
        await session.flush()
        scene = Scene(
            episode_id=episode.id, scene_number=1, location_name="Bridge", time_of_day="day"
        )
        session.add(scene)
        await session.flush()
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=1,
            visual_description="The documented stone bridge.",
        )
        session.add(shot)
        await session.commit()
        service = DirectorAgentService(
            factory, actor_id=actor.id, workspace_id=workspace.id, project_id=project.id
        )
        yield AgentWorld(service, factory, shot.id, other.id)
    await engine.dispose()


def read_shot(shot_id: UUID, call_id: str = "read-shot") -> AgentModelResponse:
    return AgentModelResponse(
        tool_calls=[
            AgentToolCall(
                call_id=call_id,
                name="shot_get",
                arguments={"shot_id": str(shot_id)},
            )
        ],
        usage={"input_tokens": 5, "output_tokens": 3},
    )


async def test_real_tool_result_reaches_model_and_answer_is_durable(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(
        read_shot(world.shot_id),
        AgentModelResponse(text="The bridge shot is ready."),
    )
    result = await world.service.run(
        thread.id,
        AgentRequest(content="Read my shot", request_key="read-1"),
        model=model,
        checkpointer=MemorySaver(),
    )
    assert result.status == "completed" and result.model_calls == 2 and result.tool_calls == 1
    assert result.assistant_message_id is not None
    messages = model.calls[1]["messages"]
    tool_messages = [message for message in messages if message.role == "tool"]
    assert len(tool_messages) == 1 and tool_messages[0].tool_call_id == "read-shot"
    assert "documented stone bridge" in tool_messages[0].content
    async with world.factory() as session:
        invocations = list(await session.scalars(select(DirectorInvocation)))
        audits = list(await session.scalars(select(DirectorToolCall)))
        assert len(invocations) == 2 and all(row.status == "completed" for row in invocations)
        assert len(audits) == 1 and audits[0].result["ok"] is True
        assert await session.scalar(select(func.count(NodeRun.id))) == 0
        assert await session.scalar(select(func.count(ProviderOperation.id))) == 0
        shot = await session.get(Shot, world.shot_id)
        assert shot and shot.version == 1 and shot.image_prompt == ""
    transcript = await world.service.read_thread(thread.id)
    assert [row["role"] for row in transcript["messages"]] == ["user", "assistant"]


async def test_request_replay_does_not_resubmit_and_changed_payload_conflicts(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(AgentModelResponse(text="What would you like to make?"))
    request = AgentRequest(content="Hello", request_key="once")
    first = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    replay = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    assert replay.turn_id == first.turn_id and len(model.calls) == 1
    with pytest.raises(ConflictError):
        await world.service.run(
            thread.id,
            AgentRequest(content="Different intent", request_key="once"),
            model=model,
            checkpointer=MemorySaver(),
        )
    assert len(model.calls) == 1
    model.responses.append(AgentModelResponse(text="We can continue with that direction."))
    continuation = await world.service.run(
        thread.id,
        AgentRequest(content="Continue our conversation", request_key="next-turn"),
        model=model,
        checkpointer=MemorySaver(),
    )
    assert continuation.status == "completed" and continuation.turn_id != first.turn_id
    history = model.calls[1]["messages"]
    assert any(message.role == "user" and message.content == "Hello" for message in history)
    assert any(
        message.role == "assistant" and message.content == "What would you like to make?"
        for message in history
    )


async def test_prompt_proposal_is_real_pending_and_never_applies(agent_world: AgentWorld) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(
        read_shot(world.shot_id),
        AgentModelResponse(
            tool_calls=[
                AgentToolCall(
                    call_id="proposal",
                    name="shot_prompt_propose",
                    arguments={
                        "shot_id": str(world.shot_id),
                        "expected_version": 1,
                        "image_prompt": "Keep the documented stone arches.",
                        "rationale": "Preserve the historical structure.",
                    },
                )
            ]
        ),
    )
    request = AgentRequest(content="Suggest a faithful image prompt", request_key="propose-once")
    result = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    assert result.status == "completed" and len(result.proposal_ids) == 1
    assert len(model.calls) == 2
    replay = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    assert replay.proposal_ids == result.proposal_ids and len(model.calls) == 2
    async with world.factory() as session:
        proposal = await session.get(DirectorProposal, result.proposal_ids[0])
        items = list(await session.scalars(select(DirectorProposalItem)))
        shot = await session.get(Shot, world.shot_id)
        assert proposal and proposal.status == "pending"
        assert len(items) == 1 and items[0].status == "pending"
        assert shot and shot.image_prompt == "" and shot.version == 1
        assert await session.scalar(select(func.count(NodeRun.id))) == 0
        assert await session.scalar(select(func.count(ProviderOperation.id))) == 0


@pytest.mark.parametrize("tool_name", ["shot_get", "shot_prompt_propose"])
async def test_scope_denial_stops_batch_and_replay_reads_failed_receipt(
    agent_world: AgentWorld, tool_name: str,
) -> None:
    world = agent_world
    async with world.factory() as session:
        original = await session.get(Shot, world.shot_id)
        sibling = Shot(
            project_id=original.project_id, scene_id=original.scene_id, shot_number=2,
            visual_description="A different shot outside the active scope.",
        )
        session.add(sibling)
        await session.commit()
        sibling_id = sibling.id
    thread = await world.service.open_thread(
        AgentThreadCreate(scope_type="shot", scope_entity_id=world.shot_id)
    )
    arguments = {"shot_id": str(sibling_id)}
    if tool_name == "shot_prompt_propose":
        arguments.update(expected_version=1, image_prompt="Outside scope", rationale="Test")
    model = ScriptedModel(AgentModelResponse(tool_calls=[
        AgentToolCall(call_id="denied", name=tool_name, arguments=arguments),
        AgentToolCall(call_id="must-not-run", name="project_get", arguments={}),
    ]))
    request = AgentRequest(content="Inspect another shot", request_key="denied-once")
    result = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    assert result.status == "failed" and result.stop_reason == "permission_denied"
    assert result.proposal_ids == [] and result.assistant_message_id is None
    assert len(model.calls) == 1 and result.tool_calls == 1
    replay = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    assert replay == result and len(model.calls) == 1
    async with world.factory() as session:
        audits = list(await session.scalars(select(DirectorToolCall)))
        assert len(audits) == 1
        assert audits[0].result["error"]["code"] == "ToolPermissionDenied"
        assert audits[0].result["error"]["retry_class"] == "none"
        assert await session.scalar(select(func.count(DirectorProposal.id))) == 0
        assert await session.scalar(select(func.count(NodeRun.id))) == 0
        assert await session.scalar(select(func.count(ProviderOperation.id))) == 0


async def test_unknown_submission_is_journaled_and_never_replayed(agent_world: AgentWorld) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(TimeoutError("possibly billed request"))
    request = AgentRequest(content="Analyze", request_key="unknown-once")
    result = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    assert result.status == "failed" and result.stop_reason == "unknown_submission"
    saved_turn = await world.service.read_turn(result.turn_id)
    assert saved_turn.transport_status == "unknown_submission"
    replay = await world.service.run(thread.id, request, model=model, checkpointer=MemorySaver())
    assert replay.turn_id == result.turn_id and len(model.calls) == 1
    async with world.factory() as session:
        invocation = await session.scalar(select(DirectorInvocation))
        assert invocation and invocation.status == "unknown_submission"
        assert "possibly billed" not in (await world.service.read_thread(thread.id)).__repr__()


async def test_stop_during_network_preserves_receipt_without_more_tools(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())

    class StopModel(ScriptedModel):
        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            async with world.factory() as session:
                turn = await session.get(DirectorTurn, kwargs["turn_id"])
                assert turn and turn.transport_status == "submission_started"
                revision = turn.revision
            await world.service.stop(
                kwargs["turn_id"],
                expected_revision=revision,
                request_key="stop",
            )
            return read_shot(world.shot_id)

    model = StopModel()
    result = await world.service.run(
        thread.id,
        AgentRequest(content="Read shot", request_key="stop-me"),
        model=model,
        checkpointer=MemorySaver(),
    )
    assert result.status == "cancelled" and len(model.calls) == 1
    async with world.factory() as session:
        assert await session.scalar(select(func.count(DirectorToolCall.id))) == 0
        assert await session.scalar(select(func.count(DirectorMessage.id))) == 1


async def test_stale_version_stops_instead_of_using_new_facts(agent_world: AgentWorld) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(read_shot(world.shot_id))
    result = await world.service.run(
        thread.id,
        AgentRequest(
            content="Read shot", request_key="stale", expected_versions={f"shot:{world.shot_id}": 2}
        ),
        model=model,
        checkpointer=MemorySaver(),
    )
    assert result.status == "stale" and len(model.calls) <= 1
    assert result.proposal_ids == []


async def test_actual_read_versions_guard_answer_after_concurrent_edit(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())

    class ConcurrentEditModel(ScriptedModel):
        async def generate(self, **kwargs):
            response = await super().generate(**kwargs)
            if len(self.calls) == 2:
                # Simulate a user editing after the Agent read, while its model is thinking.
                async with world.factory() as session:
                    shot = await session.get(Shot, world.shot_id)
                    assert shot is not None
                    shot.visual_description = "The user's revised bridge design."
                    shot.version += 1
                    await session.commit()
            return response

    model = ConcurrentEditModel(
        read_shot(world.shot_id),
        AgentModelResponse(text="An answer based on the old shot."),
    )
    result = await world.service.run(
        thread.id,
        AgentRequest(content="Inspect my shot", request_key="observed-version"),
        model=model,
        checkpointer=MemorySaver(),
    )
    assert len(model.calls) == 2
    assert result.status == "stale" and result.stop_reason == "context_stale"
    assert result.assistant_message_id is None
    async with world.factory() as session:
        turn = await session.get(DirectorTurn, result.turn_id)
        assert turn is not None and turn.input_versions == {}
        assert (
            await session.scalar(
                select(func.count(DirectorMessage.id)).where(
                    DirectorMessage.turn_id == result.turn_id,
                    DirectorMessage.role == "assistant",
                )
            )
            == 0
        )


async def test_answer_is_rechecked_after_checkpoint_before_final_commit(
    agent_world: AgentWorld,
    monkeypatch,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    finish = world.service._finish

    async def changed_after_graph(turn_id, token, reason, answer):
        if reason == "completed":
            async with world.factory() as session:
                shot = await session.get(Shot, world.shot_id)
                assert shot is not None
                shot.version += 1
                shot.visual_description = "A user changed the source after the graph completed."
                await session.commit()
        return await finish(turn_id, token, reason, answer)

    monkeypatch.setattr(world.service, "_finish", changed_after_graph)
    model = ScriptedModel(read_shot(world.shot_id), AgentModelResponse(text="Old source answer."))
    result = await world.service.run(
        thread.id,
        AgentRequest(content="Read shot", request_key="late-context-change"),
        model=model,
        checkpointer=MemorySaver(),
    )
    assert result.status == "stale" and result.assistant_message_id is None
    assert len(model.calls) == 2


async def test_thread_and_scope_cannot_cross_projects(agent_world: AgentWorld) -> None:
    world = agent_world
    other = DirectorAgentService(
        world.factory,
        actor_id=world.service.actor_id,
        workspace_id=world.service.workspace_id,
        project_id=world.other_project_id,
    )
    thread = await other.open_thread(AgentThreadCreate())
    model = ScriptedModel(AgentModelResponse(text="Must not be reached"))
    with pytest.raises(NotFoundError):
        await world.service.run(
            thread.id,
            AgentRequest(content="Read", request_key="foreign"),
            model=model,
            checkpointer=MemorySaver(),
        )
    with pytest.raises(NotFoundError):
        await other.open_thread(AgentThreadCreate(scope_type="shot", scope_entity_id=world.shot_id))
    assert model.calls == []


async def test_receipt_lookup_never_admits_missing_requests(agent_world: AgentWorld) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    key = "agent/request ? 中文"
    with pytest.raises(NotFoundError) as missing:
        await world.service.read_request(thread.id, key)
    assert missing.value.details["code"] == "AGENT_REQUEST_NOT_FOUND"
    async with world.factory() as session:
        assert await session.scalar(select(func.count(DirectorTurn.id))) == 0
        assert await session.scalar(select(func.count(DirectorInvocation.id))) == 0
    model = ScriptedModel(AgentModelResponse(text="A completed request."))
    saved = await world.service.run(
        thread.id,
        AgentRequest(content="Read", request_key=key),
        model=model,
        checkpointer=MemorySaver(),
    )
    restored = await world.service.read_request(thread.id, key)
    assert restored == saved and len(model.calls) == 1


async def test_thread_defaults_to_latest_page_and_can_read_older_messages(
    agent_world: AgentWorld,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    for index in range(4):
        await world.service.run(
            thread.id,
            AgentRequest(content=f"question-{index}", request_key=f"page-{index}"),
            model=ScriptedModel(AgentModelResponse(text=f"answer-{index}")),
            checkpointer=MemorySaver(),
        )
    latest = await world.service.read_thread(thread.id, limit=2)
    assert latest["offset"] == 6 and latest["total"] == 8
    assert latest["has_previous"] is True and latest["has_more"] is False
    assert [row["content"] for row in latest["messages"]] == ["question-3", "answer-3"]
    older = await world.service.read_thread(thread.id, limit=2, offset=0)
    assert older["has_previous"] is False and older["has_more"] is True
    assert [row["content"] for row in older["messages"]] == ["question-0", "answer-0"]


async def test_connection_revision_change_stops_before_second_model_submission(
    agent_world: AgentWorld,
    monkeypatch,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    scripted = ScriptedModel(read_shot(world.shot_id))
    binding = text_transport.ResolvedAgentTextModel(
        model_id="frozen",
        resolution={"connection_revision_id": "r1"},
        text_model=None,
        native_options={},
    )

    async def resolve(session, *, project):
        return (
            replace(binding, resolution={"connection_revision_id": "r2"})
            if scripted.calls
            else binding
        )

    async def generate(self, **kwargs):
        return await scripted.generate(**kwargs)

    monkeypatch.setattr(text_transport, "resolve_agent_text_model", resolve)
    monkeypatch.setattr(text_transport.ResolvedAgentTextModel, "generate", generate)
    result = await world.service.run(
        thread.id,
        AgentRequest(content="Read the shot", request_key="rotated-connection"),
        model=binding,
        checkpointer=MemorySaver(),
    )
    assert result.status == "stale" and len(scripted.calls) == 1
    assert result.assistant_message_id is None
    async with world.factory() as session:
        calls = list(await session.scalars(select(DirectorInvocation)))
        assert len(calls) == 1 and calls[0].model_resolution == {"connection_revision_id": "r1"}


@pytest.mark.parametrize("final_cost", [Decimal("0.20"), None, "unknown"])
async def test_reported_model_cost_is_kept_without_guessing_unknown_calls(
    agent_world: AgentWorld,
    final_cost,
) -> None:
    world = agent_world
    thread = await world.service.open_thread(AgentThreadCreate())
    model = ScriptedModel(
        read_shot(world.shot_id).model_copy(update={"reported_cost": Decimal("0.10")}),
        TimeoutError("submission outcome unknown")
        if final_cost == "unknown"
        else AgentModelResponse(text="Read complete.", reported_cost=final_cost),
    )
    result = await world.service.run(
        thread.id,
        AgentRequest(content="Read", request_key="reported-cost"),
        model=model,
        checkpointer=MemorySaver(),
    )
    assert result.status == ("failed" if final_cost == "unknown" else "completed")
    turn = await world.service.read_turn(result.turn_id)
    reported = isinstance(final_cost, Decimal)
    assert turn.cost_status == ("reported" if reported else "unknown")
    assert turn.provider_cost == (Decimal("0.30") if reported else None)
