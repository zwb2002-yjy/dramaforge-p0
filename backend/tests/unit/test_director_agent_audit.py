"""Tool receipts reuse identities and settle interrupted work without re-execution."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.contracts.agent import AgentToolCall
from app.director.agent_audit import (
    MAX_RESULT_BYTES,
    AgentToolAudit,
    fingerprint,
    public_summary,
    result_fingerprint,
)
from app.director.agent_proposals import create_agent_shot_proposal
from app.director.agent_tools import ToolContext, ToolRegistry, ToolSpec
from app.director.assistant_models import DirectorThread, DirectorToolCall
from app.director.proposal_models import DirectorProposal
from app.director.turn_models import DirectorTurn
from app.shared.base import Base
from app.shared.errors import ConflictError, NotFoundError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@dataclass
class AuditWorld:
    factory: async_sessionmaker[AsyncSession]
    context: ToolContext
    shot_id: UUID


@pytest.fixture
async def audit_world() -> AsyncIterator[AuditWorld]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        owner = User(email=f"audit-{uuid4()}@example.com", display_name="Owner", password_hash="x")
        session.add(owner)
        await session.flush()
        workspace = Workspace(name="Audit", owner_user_id=owner.id)
        session.add(workspace)
        await session.flush()
        project = Project(
            workspace_id=workspace.id,
            name="Culture",
            aspect_ratio="16:9",
            budget_limit=0,
        )
        session.add(project)
        await session.flush()
        episode = Episode(project_id=project.id, episode_number=1)
        session.add(episode)
        await session.flush()
        scene = Scene(
            episode_id=episode.id,
            scene_number=1,
            location_name="Bridge",
            time_of_day="day",
        )
        session.add(scene)
        await session.flush()
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=1,
            visual_description="Bridge",
        )
        thread = DirectorThread(
            project_id=project.id,
            scope_type="project",
            scope_entity_id=project.id,
            created_by=owner.id,
        )
        session.add_all([shot, thread])
        await session.flush()
        turn = DirectorTurn(
            project_id=project.id,
            workspace_id=workspace.id,
            actor_id=owner.id,
            thread_id=thread.id,
            turn_kind="agent",
            scope_type="project",
            scope_entity_id=project.id,
            request_key="audit-request",
            context_hash="a" * 64,
            status="thinking",
        )
        session.add(turn)
        await session.commit()
        context = ToolContext(
            actor_id=owner.id,
            workspace_id=workspace.id,
            project_id=project.id,
            turn_id=turn.id,
            thread_id=thread.id,
            scope_type="project",
            scope_entity_id=project.id,
        )
        yield AuditWorld(factory, context, shot.id)
    await engine.dispose()


def _spec(name: str = "shot_get") -> ToolSpec:
    return next(item for item in ToolRegistry().specs() if item.name == name)


def _call(world: AuditWorld, call_id: str = "read") -> AgentToolCall:
    return AgentToolCall(
        call_id=call_id,
        name="shot_get",
        arguments={"shot_id": str(world.shot_id)},
    )


async def _prepare(
    session: AsyncSession, world: AuditWorld, call: AgentToolCall, spec: ToolSpec | None = None
):
    return await AgentToolAudit(session).prepare(
        project_id=world.context.project_id,
        turn_id=world.context.turn_id,
        call=call,
        step=1,
        spec=spec or _spec(),
    )


async def _complete(
    session: AsyncSession,
    world: AuditWorld,
    call_id: str,
    result: dict[str, object],
):
    return await AgentToolAudit(session).complete(
        project_id=world.context.project_id,
        turn_id=world.context.turn_id,
        call_id=call_id,
        result=result,
        latency_ms=12,
    )


async def test_completed_receipt_reused_without_executing_and_hash_ignores_timing(
    audit_world: AuditWorld,
) -> None:
    world = audit_world
    async with world.factory() as session:
        first = await _prepare(session, world, _call(world))
        assert first.should_execute and first.result is None
        receipt = await _complete(
            session,
            world,
            "read",
            {
                "call_id": "read",
                "ok": True,
                "data": {"name": "Bridge"},
                "observed_versions": {f"shot:{world.shot_id}": 1},
                "provenance": {"source": "spoofed", "credential": "secret"},
            },
        )
        await session.commit()
    async with world.factory() as session:
        repeat = await _prepare(session, world, _call(world))
        assert not repeat.should_execute and repeat.result == receipt
        assert receipt["provenance"]["source"] == "dramaforge"
        assert receipt["result_hash"] == result_fingerprint({**receipt, "latency_ms": 999})
        assert await session.scalar(select(func.count(DirectorToolCall.id))) == 1


@pytest.mark.parametrize("changed", ["name", "version", "schema", "arguments"])
async def test_call_identity_checks_every_frozen_component(
    audit_world: AuditWorld,
    changed: str,
) -> None:
    world = audit_world
    async with world.factory() as session:
        await _prepare(session, world, _call(world))
        await session.commit()
    call, spec = _call(world), _spec()
    if changed == "name":
        call = call.model_copy(
            update={
                "name": "asset_get",
                "arguments": {"asset_id": str(uuid4())},
            }
        )
        spec = _spec("asset_get")
    elif changed == "version":
        spec = spec.model_copy(update={"version": "2"})
    elif changed == "schema":
        spec = spec.model_copy(update={"schema_hash": "b" * 64})
    else:
        call = call.model_copy(update={"arguments": {"shot_id": str(uuid4())}})
    async with world.factory() as session:
        with pytest.raises(ConflictError):
            await _prepare(session, world, call, spec)


async def test_interrupted_read_does_not_replay_and_late_success_cannot_overwrite(
    audit_world: AuditWorld,
) -> None:
    world = audit_world
    async with world.factory() as session:
        await _prepare(session, world, _call(world))
        await session.commit()
    async with world.factory() as session:
        resumed = await _prepare(session, world, _call(world))
        assert not resumed.should_execute and resumed.row.status == "failed"
        assert resumed.result and resumed.result["error"]["code"] == "TOOL_COMPLETION_UNCONFIRMED"
        original_hash = resumed.result["result_hash"]
        late = await _complete(
            session,
            world,
            "read",
            {
                "call_id": "read",
                "ok": True,
                "data": {"raw_private_data": "never expose"},
            },
        )
        assert late["ok"] is False and late["result_hash"] == original_hash
        assert late["late_outcome"]["ok"] is True and late["data"] is None
        assert "never expose" not in json.dumps(public_summary(resumed.row), default=str)
        await session.commit()


async def test_settle_only_pending_work_and_terminal_empty_receipt_is_fail_closed(
    audit_world: AuditWorld,
) -> None:
    world = audit_world
    async with world.factory() as session:
        good = await _prepare(session, world, _call(world, "done"))
        await _complete(session, world, "done", {"call_id": "done", "ok": True, "data": {}})
        waiting = await _prepare(session, world, _call(world, "waiting"))
        journal = AgentToolAudit(session)
        assert (
            await journal.settle(
                project_id=world.context.project_id,
                turn_id=world.context.turn_id,
                status="cancelled",
            )
            == 1
        )
        assert good.row.status == "completed" and waiting.row.status == "cancelled"
        assert (
            await journal.settle(project_id=world.context.project_id, turn_id=world.context.turn_id)
            == 0
        )
        waiting.row.result = {}
        await session.flush()
        repaired = await _prepare(session, world, _call(world, "waiting"))
        assert not repaired.should_execute and repaired.result["ok"] is False
        assert len(repaired.result["result_hash"]) == 64


async def test_errors_arguments_and_public_summary_do_not_leak_payloads(
    audit_world: AuditWorld,
) -> None:
    world = audit_world
    call = _call(world).model_copy(
        update={
            "arguments": {
                "shot_id": str(world.shot_id),
                "api_key": "private-api-key",
                "image_prompt": "private-prompt",
                "rationale": "private-rationale",
            }
        }
    )
    async with world.factory() as session:
        admission = await _prepare(session, world, call)
        assert "private-" not in json.dumps(admission.row.arguments)
        assert admission.row.args_hash == fingerprint(call.arguments)
        receipt = await _complete(
            session,
            world,
            "read",
            {
                "call_id": "read",
                "ok": False,
                "error": {
                    "code": "ContextStale",
                    "message": "password=private-password",
                    "details": {"api_key": "private-api-key"},
                },
            },
        )
        assert receipt["error"]["retry_class"] == "refresh_context"
        assert "private-" not in json.dumps(receipt)
        summary = public_summary(admission.row)
        assert "data" not in summary and "arguments" not in summary


async def test_oversize_and_nonfinite_results_become_bounded_hashed_errors(
    audit_world: AuditWorld,
) -> None:
    world = audit_world
    async with world.factory() as session:
        await _prepare(session, world, _call(world, "large"))
        large = await _complete(
            session,
            world,
            "large",
            {
                "call_id": "large",
                "ok": True,
                "data": {"text": "桥" * MAX_RESULT_BYTES},
            },
        )
        assert large["error"]["code"] == "ToolResultTooLarge"
        assert len(json.dumps(large).encode()) < MAX_RESULT_BYTES
        await _prepare(session, world, _call(world, "nan"))
        invalid = await _complete(
            session,
            world,
            "nan",
            {
                "call_id": "nan",
                "ok": True,
                "data": {"number": float("nan")},
            },
        )
        assert invalid["error"]["code"] == "ToolResultInvalid"
        assert invalid["result_hash"] == result_fingerprint(invalid)


async def test_proposal_and_receipt_share_transaction_and_replay_existing_id(
    audit_world: AuditWorld,
) -> None:
    world = audit_world
    call = AgentToolCall(
        call_id="propose",
        name="shot_prompt_propose",
        arguments={
            "shot_id": str(world.shot_id),
            "expected_version": 1,
            "image_prompt": "Keep the original bridge arches.",
            "rationale": "Preserve facts.",
        },
    )
    spec = _spec(call.name)
    for rollback in (True, False):
        async with world.factory() as session:
            prepared = await _prepare(session, world, call, spec)
            assert prepared.should_execute
            proposal = await create_agent_shot_proposal(
                session,
                context=world.context,
                arguments=dict(call.arguments),
                call_id=call.call_id,
            )
            saved = await _complete(
                session,
                world,
                call.call_id,
                {
                    "call_id": call.call_id,
                    "ok": True,
                    "data": proposal.model_dump(mode="json"),
                },
            )
            if rollback:
                await session.rollback()
            else:
                await session.commit()
        if rollback:
            async with world.factory() as session:
                assert await session.scalar(select(func.count(DirectorProposal.id))) == 0
                assert await session.scalar(select(func.count(DirectorToolCall.id))) == 0
    async with world.factory() as session:
        replay = await _prepare(session, world, call, spec)
        assert not replay.should_execute and replay.result == saved
        assert await session.scalar(select(func.count(DirectorProposal.id))) == 1
        shot = await session.get(Shot, world.shot_id)
        assert shot and shot.image_prompt == "" and shot.version == 1


async def test_wrong_project_cannot_prepare_or_complete(audit_world: AuditWorld) -> None:
    world = audit_world
    async with world.factory() as session:
        with pytest.raises(NotFoundError):
            await AgentToolAudit(session).prepare(
                project_id=uuid4(),
                turn_id=world.context.turn_id,
                call=_call(world),
                step=1,
                spec=_spec(),
            )
