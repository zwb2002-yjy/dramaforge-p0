"""Real migration-head proof for Agent scope, journal uniqueness and Worker isolation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.contracts.agent import AgentModelResponse, AgentToolCall
from app.director.agent_audit import AgentToolAudit
from app.director.agent_service import AgentRequest, AgentThreadCreate, DirectorAgentService
from app.director.agent_tools import ToolExecutor
from app.director.assistant_models import DirectorMessage, DirectorThread, DirectorToolCall
from app.director.invocation_models import DirectorInvocation
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.director.turn_models import DirectorTurn
from app.execution.models import NodeRun, ProviderOperation
from app.shared.errors import ConflictError
from app.shared.model_registry import load_all_models
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine, delete, event, func, insert, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
    _sync_url,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


@dataclass(frozen=True)
class Tenant:
    actor_id: UUID
    workspace_id: UUID
    project_id: UUID
    thread_id: UUID
    turn_id: UUID
    tool_id: UUID


@dataclass(frozen=True)
class AgentDatabase:
    engine: Engine
    tenants: tuple[Tenant, Tenant]


def _turn(tenant: Tenant, **changes) -> DirectorTurn:
    values = {
        "workspace_id": tenant.workspace_id,
        "project_id": tenant.project_id,
        "actor_id": tenant.actor_id,
        "thread_id": tenant.thread_id,
        "turn_kind": "agent",
        "scope_type": "project",
        "scope_entity_id": tenant.project_id,
        "request_key": uuid4().hex,
        "context_hash": "a" * 64,
        "status": "completed",
    }
    return DirectorTurn(**{**values, **changes})


def _tool(tenant: Tenant, **changes) -> DirectorToolCall:
    values = {
        "project_id": tenant.project_id,
        "turn_id": tenant.turn_id,
        "step": 1,
        "call_id": uuid4().hex,
        "tool_name": "project_get",
        "tool_version": "1",
        "schema_hash": "b" * 64,
        "args_hash": "c" * 64,
        "arguments": {},
        "result": {"ok": True},
        "status": "completed",
    }
    return DirectorToolCall(**{**values, **changes})


def _app_scope(connection: Connection, tenant: Tenant) -> None:
    connection.execute(text("SET LOCAL ROLE dramaforge_app"))
    connection.execute(
        text(
            "SELECT set_config('app.current_user_id', :user, true), "
            "set_config('app.current_workspace_id', :workspace, true), "
            "set_config('app.current_project_id', :project, true)"
        ),
        {
            "user": str(tenant.actor_id),
            "workspace": str(tenant.workspace_id),
            "project": str(tenant.project_id),
        },
    )


@pytest.fixture(scope="module")
def agent_database() -> Iterator[AgentDatabase]:
    # One test-owned database for this module; no shared quality fixture is changed.
    dbname = f"dramaforge_agent_{uuid4().hex[:8]}"
    asyncio.run(_create_database(dbname))
    engine = create_engine(_sync_url(dbname))
    try:
        _alembic(dbname)
        load_all_models()
        tenants = []
        with Session(engine, expire_on_commit=False) as session:
            for _index in range(2):
                actor = User(
                    email=f"agent-{uuid4().hex}@example.com",
                    display_name="Owner",
                    password_hash="isolated-test",
                )
                session.add(actor)
                session.flush()
                workspace = Workspace(owner_user_id=actor.id, name="Agent workspace")
                session.add(workspace)
                session.flush()
                project = Project(
                    workspace_id=workspace.id, name="Culture", aspect_ratio="16:9", budget_limit=0
                )
                session.add(project)
                session.flush()
                thread = DirectorThread(
                    project_id=project.id,
                    scope_type="project",
                    scope_entity_id=project.id,
                    created_by=actor.id,
                )
                session.add(thread)
                session.flush()
                tenant = Tenant(actor.id, workspace.id, project.id, thread.id, uuid4(), uuid4())
                # Identical request/call identities are valid in distinct scopes.
                session.add(_turn(tenant, id=tenant.turn_id, request_key="same-request"))
                session.flush()
                session.add(_tool(tenant, id=tenant.tool_id, call_id="same-call"))
                session.add(
                    DirectorMessage(
                        project_id=tenant.project_id,
                        thread_id=tenant.thread_id,
                        turn_id=tenant.turn_id,
                        ordinal=0,
                        role="user",
                        content="Read the project",
                        created_by=tenant.actor_id,
                    )
                )
                tenants.append(tenant)
            session.commit()
        yield AgentDatabase(engine, (tenants[0], tenants[1]))
    finally:
        engine.dispose()
        asyncio.run(_drop_database(dbname))


@pytest.mark.parametrize(
    "entity,constraint",
    [
        ("tool", "fk_director_tool_call_turn_scope"),
        ("message", "fk_director_message_turn_scope"),
        ("thread_link", "fk_director_turn_thread_scope"),
        ("origin", "fk_director_turn_origin_scope"),
    ],
)
def test_composite_scope_rejects_cross_project_links_even_for_admin(
    agent_database: AgentDatabase,
    entity: str,
    constraint: str,
) -> None:
    own, other = agent_database.tenants
    if entity == "tool":
        row = _tool(own, turn_id=other.turn_id)
    elif entity == "message":
        row = DirectorMessage(
            project_id=own.project_id,
            thread_id=own.thread_id,
            turn_id=other.turn_id,
            ordinal=1,
            role="assistant",
            content="forged",
        )
    elif entity == "thread_link":
        row = _turn(own, thread_id=other.thread_id)
    else:
        row = _turn(own, turn_kind="workflow", origin_agent_turn_id=other.turn_id)
    with Session(agent_database.engine) as session:
        session.add(row)
        with pytest.raises(IntegrityError) as rejected:
            session.flush()
        assert rejected.value.orig.sqlstate == "23503"
        assert rejected.value.orig.diag.constraint_name == constraint
        session.rollback()


@pytest.mark.parametrize(
    "entity,constraint",
    [
        ("request", "uq_director_turn_request"),
        ("tool", "uq_director_tool_call_id"),
        ("message", "uq_director_message_turn_ordinal"),
    ],
)
def test_duplicate_request_call_and_message_identity_cannot_create_second_fact(
    agent_database: AgentDatabase,
    entity: str,
    constraint: str,
) -> None:
    own = agent_database.tenants[0]
    if entity == "request":
        row = _turn(own, request_key="same-request")
    elif entity == "tool":
        row = _tool(own, call_id="same-call")
    else:
        row = DirectorMessage(
            project_id=own.project_id,
            thread_id=own.thread_id,
            turn_id=own.turn_id,
            ordinal=0,
            role="user",
            content="duplicate",
        )
    with Session(agent_database.engine) as session:
        session.add(row)
        with pytest.raises(IntegrityError) as rejected:
            session.flush()
        assert rejected.value.orig.sqlstate == "23505"
        assert rejected.value.orig.diag.constraint_name == constraint
        session.rollback()


def test_tool_audit_rls_allows_owned_crud_and_blocks_other_project(
    agent_database: AgentDatabase,
) -> None:
    own, other = agent_database.tenants
    with agent_database.engine.connect() as connection, connection.begin():
        enabled, forced = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'director_tool_calls'::regclass"
            )
        ).one()
        assert enabled and forced
        _app_scope(connection, own)
        visible = connection.execute(select(DirectorToolCall.id)).scalars().all()
        assert visible == [own.tool_id]
        for command in (
            update(DirectorToolCall)
            .where(DirectorToolCall.id == other.tool_id)
            .values(status="failed"),
            delete(DirectorToolCall).where(DirectorToolCall.id == other.tool_id),
        ):
            assert connection.execute(command).rowcount == 0
        inserted = uuid4()
        values = dict(
            id=inserted,
            project_id=own.project_id,
            turn_id=own.turn_id,
            step=2,
            call_id="app-insert",
            tool_name="project_get",
            tool_version="1",
            schema_hash="b" * 64,
            args_hash="c" * 64,
            arguments={},
            result={},
            status="pending",
        )
        connection.execute(insert(DirectorToolCall).values(**values))
        assert (
            connection.execute(
                update(DirectorToolCall)
                .where(DirectorToolCall.id == inserted)
                .values(status="completed", result={"ok": True})
            ).rowcount
            == 1
        )
        assert (
            connection.execute(
                delete(DirectorToolCall).where(DirectorToolCall.id == inserted)
            ).rowcount
            == 1
        )
        with pytest.raises(DBAPIError) as denied, connection.begin_nested():
            connection.execute(
                insert(DirectorToolCall).values(
                    **{
                        **values,
                        "id": uuid4(),
                        "project_id": other.project_id,
                        "turn_id": other.turn_id,
                        "call_id": "foreign-insert",
                    }
                )
            )
        assert denied.value.orig.sqlstate == "42501"


def test_workflow_recovery_scans_exclude_agent_turns_and_keep_function_permissions(
    agent_database: AgentDatabase,
) -> None:
    own = agent_database.tenants[0]
    expired = datetime.now(UTC) - timedelta(minutes=10)
    expected: dict[str, set[UUID]] = {"recoverable": set(), "reconcilable": set()}
    excluded: set[UUID] = set()
    with Session(agent_database.engine, expire_on_commit=False) as session:
        for kind in ("agent", "workflow"):
            for scan in expected:
                turn = _turn(
                    own,
                    turn_kind=kind,
                    status="thinking" if scan == "recoverable" else "awaiting_user",
                    deadline=expired if scan == "recoverable" else None,
                    node_run_ids=[] if scan == "recoverable" else [str(uuid4())],
                    engine_version="isolated-test",
                    state_schema_version="isolated-test",
                    runtime_execution_id=uuid4(),
                    runtime_revision=1,
                )
                session.add(turn)
                session.flush()
                (excluded if kind == "agent" else expected[scan]).add(turn.id)
        # Existing-style creation keeps workflow defaults without invented context.
        legacy = DirectorTurn(
            project_id=own.project_id,
            workspace_id=own.workspace_id,
            actor_id=own.actor_id,
            scope_type="project",
            scope_entity_id=own.project_id,
            request_key="legacy-default",
            context_hash="d" * 64,
            status="completed",
        )
        session.add(legacy)
        session.commit()
        session.refresh(legacy)
        assert legacy.turn_kind == "workflow" and legacy.agent_control_epoch == 0
        assert legacy.thread_id is None and legacy.runtime_execution_id is None
    with agent_database.engine.connect() as connection, connection.begin():
        _app_scope(connection, own)
        scans = {
            "recoverable": text(
                "SELECT turn_id FROM app.recoverable_director_turn_contexts("
                "50, CAST(:stale AS timestamptz))"
            ),
            "reconcilable": text(
                "SELECT turn_id FROM app.reconcilable_director_turn_contexts(50, NULL)"
            ),
        }
        for name, query in scans.items():
            actual = set(connection.execute(query, {"stale": expired}).scalars())
            assert expected[name] <= actual
            assert not actual.intersection(excluded)
        for signature in (
            "app.recoverable_director_turn_contexts(integer,timestamptz)",
            "app.reconcilable_director_turn_contexts(integer,uuid)",
        ):
            security = connection.execute(
                text(
                    "SELECT p.prosecdef, r.rolname, "
                    "NOT EXISTS (SELECT 1 FROM aclexplode(COALESCE(p.proacl, "
                    "acldefault('f', p.proowner))) a WHERE a.grantee = 0 "
                    "AND a.privilege_type = 'EXECUTE') AS no_public "
                    "FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner "
                    "WHERE p.oid = CAST(:signature AS regprocedure)"
                ),
                {"signature": signature},
            ).one()
            assert security.prosecdef and security.no_public
            assert security.rolname == "dramaforge_worker_resolver"


@dataclass(frozen=True)
class AgentRuntime:
    database: AgentDatabase
    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]
    actor_id: UUID
    workspace_id: UUID
    project_id: UUID
    thread_id: UUID

    def service(self) -> DirectorAgentService:
        return DirectorAgentService(
            self.factory,
            actor_id=self.actor_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
        )


@pytest.fixture
async def agent_runtime(agent_database: AgentDatabase) -> AsyncIterator[AgentRuntime]:
    # Each scenario owns a project/thread; existing migration/RLS scenarios stay untouched.
    with Session(agent_database.engine, expire_on_commit=False) as session:
        actor = User(
            email=f"runtime-{uuid4()}@example.com",
            display_name="Owner",
            password_hash="x",
        )
        session.add(actor)
        session.flush()
        workspace = Workspace(owner_user_id=actor.id, name="Runtime")
        session.add(workspace)
        session.flush()
        project = Project(
            workspace_id=workspace.id,
            name="Concurrent culture",
            aspect_ratio="16:9",
            budget_limit=0,
        )
        session.add(project)
        session.commit()
    dbname = agent_database.engine.url.database
    assert dbname is not None
    engine = create_async_engine(
        _async_url(dbname),
        connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = DirectorAgentService(
        factory,
        actor_id=actor.id,
        workspace_id=workspace.id,
        project_id=project.id,
    )
    try:
        thread = await service.open_thread(AgentThreadCreate())
        async with factory() as app_session:
            assert await app_session.scalar(text("SELECT current_user")) == "dramaforge_app"
        yield AgentRuntime(
            agent_database,
            engine,
            factory,
            actor.id,
            workspace.id,
            project.id,
            thread.id,
        )
    finally:
        await engine.dispose()


class BarrierModel:
    resolution = {"model_id": "isolated-fake-text", "deployment_revision": "fixed"}

    def __init__(self, response: AgentModelResponse) -> None:
        self.response = response
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def generate(self, **_kwargs) -> AgentModelResponse:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.response


async def _cancel_pending(*tasks: asyncio.Task) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_agent_concurrent_admission_has_one_model_submission(
    agent_runtime: AgentRuntime,
) -> None:
    runtime = agent_runtime
    first, second = runtime.service(), runtime.service()
    request = AgentRequest(content="Help plan the cultural film", request_key="concurrent-once")
    model = BarrierModel(AgentModelResponse(text="We can start from your source materials."))
    admission_requests = 0
    both_requested_lock = asyncio.Event()

    def observe_project_locks(_conn, _cursor, statement, _params, _context, _many):
        nonlocal admission_requests
        if "FROM projects" in statement and "FOR UPDATE" in statement:
            admission_requests += 1
            if admission_requests >= 2:
                both_requested_lock.set()

    event.listen(runtime.engine.sync_engine, "before_cursor_execute", observe_project_locks)
    tasks: list[asyncio.Task] = []
    try:
        async with asyncio.timeout(20):
            # Hold the real project row until both independent app connections request it.
            # This deterministically exercises first-admission serialization, not only replay.
            with runtime.database.engine.connect() as blocker:
                transaction = blocker.begin()
                try:
                    blocker.execute(
                        select(Project.id)
                        .where(
                            Project.id == runtime.project_id,
                        )
                        .with_for_update()
                    )
                    tasks = [
                        asyncio.create_task(
                            service.run(
                                runtime.thread_id,
                                request,
                                model=model,
                                checkpointer=MemorySaver(),
                            )
                        )
                        for service in (first, second)
                    ]
                    await both_requested_lock.wait()
                finally:
                    transaction.rollback()
            await model.started.wait()
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            assert len(done) == 1 and len(pending) == 1
            receipt = next(iter(done)).result()
            assert receipt.status == "thinking" and model.calls == 1
            with pytest.raises(ConflictError):
                await second.run(
                    runtime.thread_id,
                    request.model_copy(update={"content": "A different request"}),
                    model=model,
                    checkpointer=MemorySaver(),
                )
            with pytest.raises(ConflictError):
                await second.run(
                    runtime.thread_id,
                    request.model_copy(update={"request_key": "concurrent-other"}),
                    model=model,
                    checkpointer=MemorySaver(),
                )
            # Reads complete from another connection while the model remains suspended.
            current = await second.read_turn(receipt.turn_id)
            assert current.transport_status == "submission_started"
            model.release.set()
            results = await asyncio.gather(*tasks)
            assert {item.turn_id for item in results} == {receipt.turn_id}
            assert any(item.status == "completed" for item in results)
            assert model.calls == 1
        with Session(runtime.database.engine) as session:
            assert (
                session.scalar(
                    select(func.count(DirectorTurn.id)).where(
                        DirectorTurn.project_id == runtime.project_id,
                    )
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count(DirectorInvocation.id)).where(
                        DirectorInvocation.project_id == runtime.project_id,
                    )
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count(DirectorMessage.id)).where(
                        DirectorMessage.project_id == runtime.project_id,
                        DirectorMessage.role == "user",
                    )
                )
                == 1
            )
    finally:
        model.release.set()
        await _cancel_pending(*tasks)
        event.remove(runtime.engine.sync_engine, "before_cursor_execute", observe_project_locks)


@pytest.mark.asyncio
async def test_agent_stop_survives_fresh_reader_and_late_read_receipt(
    agent_runtime: AgentRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = agent_runtime
    entered = asyncio.Event()
    release = asyncio.Event()
    original_execute = ToolExecutor.execute

    async def suspended_read(self, **kwargs):
        if kwargs["context"].project_id == runtime.project_id:
            entered.set()
            await release.wait()
        return await original_execute(self, **kwargs)

    monkeypatch.setattr(ToolExecutor, "execute", suspended_read)
    model = BarrierModel(
        AgentModelResponse(
            tool_calls=[
                AgentToolCall(call_id="read-project", name="project_get", arguments={}),
            ]
        )
    )
    model.release.set()
    request = AgentRequest(content="Inspect this project", request_key="stop-read")
    running = asyncio.create_task(
        runtime.service().run(
            runtime.thread_id,
            request,
            model=model,
            checkpointer=MemorySaver(),
        )
    )
    try:
        async with asyncio.timeout(20):
            # ToolCall running has committed; the original handler cannot clean up.
            await entered.wait()
            with Session(runtime.database.engine) as session:
                turn = session.scalar(
                    select(DirectorTurn).where(
                        DirectorTurn.project_id == runtime.project_id,
                    )
                )
                assert turn is not None
                turn_id, revision = turn.id, turn.revision
                audit = session.scalar(
                    select(DirectorToolCall).where(
                        DirectorToolCall.turn_id == turn_id,
                    )
                )
                assert audit is not None and audit.status == "running"
            stopped = await runtime.service().stop(
                turn_id,
                expected_revision=revision,
                request_key="stop-once",
            )
            fresh = runtime.service()
            restored = await fresh.read_turn(turn_id)
            replay = await fresh.replay(runtime.thread_id, request)
            assert stopped.status == restored.status == "cancelled"
            assert replay is not None and replay.turn_id == turn_id and replay.status == "cancelled"
            assert not running.done()  # Cleanup is proven without assistance from the live handler.
            with Session(runtime.database.engine) as session:
                audit = session.scalar(
                    select(DirectorToolCall).where(
                        DirectorToolCall.turn_id == turn_id,
                    )
                )
                assert audit is not None and audit.status == "cancelled"
                before_hash = audit.result["result_hash"]
                assert audit.result["ok"] is False and len(before_hash) == 64
            release.set()
            result = await running
            assert result.status == "cancelled" and result.assistant_message_id is None
            assert model.calls == 1
        with Session(runtime.database.engine) as session:
            audit = session.scalar(
                select(DirectorToolCall).where(
                    DirectorToolCall.turn_id == turn_id,
                )
            )
            assert audit is not None and audit.status == "cancelled"
            assert audit.result["result_hash"] == before_hash
            assert audit.result["late_outcome"]["ok"] is True
            assert (
                session.scalar(
                    select(func.count(NodeRun.id)).where(
                        NodeRun.project_id == runtime.project_id,
                    )
                )
                == 0
            )
            # This module's isolated database has no media operations; checking
            # all rows also catches an orphan operation without a NodeRun.
            assert session.scalar(select(func.count(ProviderOperation.id))) == 0
    finally:
        release.set()
        await _cancel_pending(running)


@pytest.mark.asyncio
async def test_expired_agent_recovery_and_late_model_result_do_not_deadlock_or_resubmit(
    agent_runtime: AgentRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = agent_runtime
    model = BarrierModel(AgentModelResponse(text="A late model answer."))
    request = AgentRequest(content="Plan the film", request_key="expired-model")
    running = asyncio.create_task(
        runtime.service().run(
            runtime.thread_id,
            request,
            model=model,
            checkpointer=MemorySaver(),
        )
    )
    recovery_locked = asyncio.Event()
    release_recovery = asyncio.Event()
    late_turn_lock_requested = asyncio.Event()
    fresh = runtime.service()
    original_recover = fresh._recover_expired
    recovered_invocation_states: list[str] = []

    async def paused_recovery(session, turn):
        recovery_locked.set()  # read_turn already owns the actual PG Turn row lock.
        await release_recovery.wait()
        await original_recover(session, turn)
        recovered_invocation_states.extend(
            await session.scalars(
                select(DirectorInvocation.status).where(DirectorInvocation.turn_id == turn.id),
            )
        )

    def observe_late_turn_lock(_conn, _cursor, statement, _params, _context, _many):
        if (
            recovery_locked.is_set()
            and "FROM director_turns" in statement
            and "FOR UPDATE" in statement
        ):
            late_turn_lock_requested.set()

    monkeypatch.setattr(fresh, "_recover_expired", paused_recovery)
    recovery = None
    listener_added = False
    try:
        async with asyncio.timeout(20):
            await model.started.wait()
            with Session(runtime.database.engine) as session:
                turn = session.scalar(
                    select(DirectorTurn).where(
                        DirectorTurn.project_id == runtime.project_id,
                    )
                )
                assert turn is not None and turn.transport_status == "submission_started"
                turn_id = turn.id
                turn.agent_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                session.commit()
            recovery = asyncio.create_task(fresh.read_turn(turn_id))
            await recovery_locked.wait()
            event.listen(
                runtime.engine.sync_engine,
                "before_cursor_execute",
                observe_late_turn_lock,
            )
            listener_added = True
            model.release.set()
            await late_turn_lock_requested.wait()
            # A reversed Invocation -> Turn completion lock would deadlock here.
            release_recovery.set()
            restored, result = await asyncio.gather(recovery, running)
            assert restored.status == result.status == "failed"
            assert recovered_invocation_states == ["unknown_submission"]
            assert result.stop_reason == "unknown_submission"
            assert result.assistant_message_id is None
            replay = await runtime.service().run(
                runtime.thread_id,
                request,
                model=model,
                checkpointer=MemorySaver(),
            )
            assert replay.turn_id == turn_id and replay.status == "failed" and model.calls == 1
        with Session(runtime.database.engine) as session:
            invocations = list(
                session.scalars(
                    select(DirectorInvocation).where(
                        DirectorInvocation.turn_id == turn_id,
                    )
                )
            )
            assert len(invocations) == 1 and invocations[0].status == "completed"
            assert invocations[0].validated_output["text"] == "A late model answer."
            assert (
                session.scalar(
                    select(func.count(DirectorToolCall.id)).where(
                        DirectorToolCall.turn_id == turn_id,
                    )
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count(DirectorMessage.id)).where(
                        DirectorMessage.turn_id == turn_id,
                        DirectorMessage.role == "assistant",
                    )
                )
                == 0
            )
    finally:
        model.release.set()
        release_recovery.set()
        await _cancel_pending(*([running, recovery] if recovery is not None else [running]))
        if listener_added:
            event.remove(
                runtime.engine.sync_engine,
                "before_cursor_execute",
                observe_late_turn_lock,
            )


@pytest.mark.asyncio
async def test_agent_stop_marks_inflight_model_unknown_without_reviving_on_late_result(
    agent_runtime: AgentRuntime,
) -> None:
    runtime = agent_runtime
    model = BarrierModel(AgentModelResponse(text="This answer arrived after stop."))
    request = AgentRequest(content="Analyze this film", request_key="stop-model")
    running = asyncio.create_task(
        runtime.service().run(
            runtime.thread_id,
            request,
            model=model,
            checkpointer=MemorySaver(),
        )
    )
    try:
        async with asyncio.timeout(20):
            await model.started.wait()
            with Session(runtime.database.engine) as session:
                turn = session.scalar(
                    select(DirectorTurn).where(
                        DirectorTurn.project_id == runtime.project_id,
                    )
                )
                assert turn is not None
                turn_id, revision = turn.id, turn.revision
            await runtime.service().stop(
                turn_id,
                expected_revision=revision,
                request_key="stop-inflight-model",
            )
            saved = await runtime.service().read_turn(turn_id)
            assert saved.status == "cancelled" and saved.transport_status == "unknown_submission"
            assert not running.done()
            with Session(runtime.database.engine) as session:
                assert (
                    session.scalar(
                        select(DirectorInvocation.status).where(
                            DirectorInvocation.turn_id == turn_id,
                        )
                    )
                    == "unknown_submission"
                )
            model.release.set()
            result = await running
            assert result.status == "cancelled" and result.assistant_message_id is None
            replay = await runtime.service().run(
                runtime.thread_id,
                request,
                model=model,
                checkpointer=MemorySaver(),
            )
            assert replay.turn_id == turn_id and replay.status == "cancelled" and model.calls == 1
        with Session(runtime.database.engine) as session:
            invocation = session.scalar(
                select(DirectorInvocation).where(
                    DirectorInvocation.turn_id == turn_id,
                )
            )
            assert invocation is not None and invocation.status == "completed"
            assert invocation.validated_output["text"] == "This answer arrived after stop."
            assert (
                session.scalar(
                    select(func.count(DirectorMessage.id)).where(
                        DirectorMessage.turn_id == turn_id,
                        DirectorMessage.role == "assistant",
                    )
                )
                == 0
            )
    finally:
        model.release.set()
        await _cancel_pending(running)


def _seed_proposal_shot(runtime: AgentRuntime) -> UUID:
    with Session(runtime.database.engine, expire_on_commit=False) as session:
        episode = Episode(project_id=runtime.project_id, episode_number=1)
        session.add(episode)
        session.flush()
        scene = Scene(
            episode_id=episode.id,
            scene_number=1,
            location_name="Historic bridge",
            time_of_day="day",
        )
        session.add(scene)
        session.flush()
        shot = Shot(
            project_id=runtime.project_id,
            scene_id=scene.id,
            shot_number=1,
            visual_description="Original bridge",
            image_prompt="Original prompt",
        )
        session.add(shot)
        session.commit()
        return shot.id


def _proposal_response(shot_id: UUID) -> AgentModelResponse:
    return AgentModelResponse(
        tool_calls=[
            AgentToolCall(
                call_id="propose-atomic",
                name="shot_prompt_propose",
                arguments={
                    "shot_id": str(shot_id),
                    "expected_version": 1,
                    "image_prompt": "Keep the documented bridge arches.",
                    "rationale": "Preserve historical evidence.",
                },
            )
        ]
    )


def _assert_no_media_or_shot_mutation(runtime: AgentRuntime, shot_id: UUID) -> None:
    with Session(runtime.database.engine) as session:
        shot = session.get(Shot, shot_id)
        assert shot is not None and shot.version == 1 and shot.image_prompt == "Original prompt"
        assert (
            session.scalar(
                select(func.count(NodeRun.id)).where(
                    NodeRun.project_id == runtime.project_id,
                )
            )
            == 0
        )
        assert session.scalar(select(func.count(ProviderOperation.id))) == 0


@pytest.mark.asyncio
async def test_cancelling_proposal_before_receipt_rolls_back_all_proposal_facts(
    agent_runtime: AgentRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = agent_runtime
    shot_id = _seed_proposal_shot(runtime)
    service = runtime.service()
    model = BarrierModel(_proposal_response(shot_id))
    model.release.set()
    request = AgentRequest(
        content="Suggest a bridge prompt",
        request_key="cancel-proposal-transaction",
    )
    proposal_flushed = asyncio.Event()
    release_proposal = asyncio.Event()
    finish_entered = asyncio.Event()
    release_finish = asyncio.Event()
    original_complete = AgentToolAudit.complete
    original_finish = service._finish
    observed_turn_id: UUID | None = None

    async def pause_receipt(self, **kwargs):
        nonlocal observed_turn_id
        if kwargs["project_id"] == runtime.project_id and kwargs["call_id"] == "propose-atomic":
            observed_turn_id = kwargs["turn_id"]
            # These are flushed real PG rows in the still-uncommitted proposal transaction.
            for row_type in (DirectorProposal, DirectorProposalItem, DirectorToolCall):
                assert (
                    await self._session.scalar(
                        select(func.count(row_type.id)).where(
                            row_type.project_id == runtime.project_id,
                        )
                    )
                    == 1
                )
            proposal_flushed.set()
            await release_proposal.wait()
        return await original_complete(self, **kwargs)

    async def pause_finish(*args, **kwargs):
        # This callback begins only after the proposal session has rolled back on cancellation.
        finish_entered.set()
        await release_finish.wait()
        return await original_finish(*args, **kwargs)

    monkeypatch.setattr(AgentToolAudit, "complete", pause_receipt)
    monkeypatch.setattr(service, "_finish", pause_finish)
    running = asyncio.create_task(
        service.run(
            runtime.thread_id,
            request,
            model=model,
            checkpointer=MemorySaver(),
        )
    )
    try:
        async with asyncio.timeout(20):
            await proposal_flushed.wait()
            assert observed_turn_id is not None
            with Session(runtime.database.engine) as session:
                # A second connection cannot see any partial proposal or receipt.
                for row_type in (DirectorProposal, DirectorProposalItem, DirectorToolCall):
                    assert (
                        session.scalar(
                            select(func.count(row_type.id)).where(
                                row_type.project_id == runtime.project_id,
                            )
                        )
                        == 0
                    )
            running.cancel()
            await finish_entered.wait()
            fresh = runtime.service()
            current = await fresh.read_turn(observed_turn_id)
            stopped = await fresh.stop(
                observed_turn_id,
                expected_revision=current.revision,
                request_key="stop-after-proposal-rollback",
            )
            assert stopped.status == "cancelled"
            replay = await fresh.replay(runtime.thread_id, request)
            assert replay is not None and replay.status == "cancelled" and replay.proposal_ids == []
            release_finish.set()
            with pytest.raises(asyncio.CancelledError):
                await running
            again = await runtime.service().run(
                runtime.thread_id,
                request,
                model=model,
                checkpointer=MemorySaver(),
            )
            assert again.status == "cancelled" and again.proposal_ids == [] and model.calls == 1
        with Session(runtime.database.engine) as session:
            for row_type in (DirectorProposal, DirectorProposalItem, DirectorToolCall):
                assert (
                    session.scalar(
                        select(func.count(row_type.id)).where(
                            row_type.project_id == runtime.project_id,
                        )
                    )
                    == 0
                )
            invocation = session.scalar(
                select(DirectorInvocation).where(
                    DirectorInvocation.project_id == runtime.project_id,
                )
            )
            assert invocation is not None and invocation.status == "completed"
        _assert_no_media_or_shot_mutation(runtime, shot_id)
    finally:
        release_proposal.set()
        release_finish.set()
        await _cancel_pending(running)


@pytest.mark.asyncio
async def test_stop_after_proposal_commit_preserves_one_pending_proposal_and_receipt(
    agent_runtime: AgentRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = agent_runtime
    shot_id = _seed_proposal_shot(runtime)
    service = runtime.service()
    model = BarrierModel(_proposal_response(shot_id))
    model.release.set()
    request = AgentRequest(content="Suggest a bridge prompt", request_key="committed-proposal-stop")
    finish_entered = asyncio.Event()
    release_finish = asyncio.Event()
    original_finish = service._finish

    async def pause_finish(*args, **kwargs):
        # The proposal tool returned only after its receipt/proposal transaction committed.
        finish_entered.set()
        await release_finish.wait()
        return await original_finish(*args, **kwargs)

    monkeypatch.setattr(service, "_finish", pause_finish)
    running = asyncio.create_task(
        service.run(
            runtime.thread_id,
            request,
            model=model,
            checkpointer=MemorySaver(),
        )
    )
    try:
        async with asyncio.timeout(20):
            await finish_entered.wait()
            with Session(runtime.database.engine) as session:
                turn = session.scalar(
                    select(DirectorTurn).where(
                        DirectorTurn.project_id == runtime.project_id,
                    )
                )
                assert turn is not None and turn.status == "thinking"
                turn_id, proposal_id = turn.id, turn.proposal_id
                assert proposal_id is not None
                audit = session.scalar(
                    select(DirectorToolCall).where(
                        DirectorToolCall.turn_id == turn_id,
                    )
                )
                assert audit is not None and audit.status == "completed" and audit.result["ok"]
                receipt_hash = audit.result["result_hash"]
                assert audit.result["data"]["proposal_ids"] == [str(proposal_id)]
                proposal = session.get(DirectorProposal, proposal_id)
                assert proposal is not None and proposal.status == "pending"
            fresh = runtime.service()
            current = await fresh.read_turn(turn_id)
            stopped = await fresh.stop(
                turn_id,
                expected_revision=current.revision,
                request_key="stop-after-proposal-commit",
            )
            assert stopped.status == "cancelled" and stopped.proposal_ids == [proposal_id]
            release_finish.set()
            result = await running
            assert result.status == "cancelled" and result.proposal_ids == [proposal_id]
            replay = await runtime.service().run(
                runtime.thread_id,
                request,
                model=model,
                checkpointer=MemorySaver(),
            )
            assert replay.status == "cancelled" and replay.proposal_ids == [proposal_id]
            assert model.calls == 1
        with Session(runtime.database.engine) as session:
            for row_type in (DirectorProposal, DirectorProposalItem, DirectorToolCall):
                assert (
                    session.scalar(
                        select(func.count(row_type.id)).where(
                            row_type.project_id == runtime.project_id,
                        )
                    )
                    == 1
                )
            proposal = session.get(DirectorProposal, proposal_id)
            item = session.scalar(
                select(DirectorProposalItem).where(
                    DirectorProposalItem.proposal_id == proposal_id,
                )
            )
            audit = session.scalar(
                select(DirectorToolCall).where(
                    DirectorToolCall.turn_id == turn_id,
                )
            )
            assert proposal is not None and proposal.status == "pending"
            assert item is not None and item.status == "pending"
            assert audit is not None and audit.status == "completed"
            assert audit.result["result_hash"] == receipt_hash
            assert (
                session.scalar(
                    select(func.count(DirectorMessage.id)).where(
                        DirectorMessage.turn_id == turn_id,
                        DirectorMessage.role == "assistant",
                    )
                )
                == 0
            )
        _assert_no_media_or_shot_mutation(runtime, shot_id)
    finally:
        release_finish.set()
        await _cancel_pending(running)
