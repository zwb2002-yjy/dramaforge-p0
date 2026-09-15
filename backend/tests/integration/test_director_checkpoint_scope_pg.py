"""D5 PostgreSQL proof for the migrated, project-scoped checkpoint store."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from app.config import Settings
from app.contracts.director_runtime import ResumeSignal, RuntimeInput, RuntimeScope
from app.director.assistant_models import DirectorThread
from app.director.proposal_models import DirectorProposal
from app.director.runtime.checkpoint import scoped_checkpoint_dsn, scoped_checkpointer
from app.director.runtime.control import DirectorRuntimeControlService
from app.director.runtime.executor import DirectorRuntimeExecutor
from app.director.runtime.langgraph_adapter import LangGraphDirectorRuntime
from app.director.runtime.models import DirectorRuntimeControl
from app.director.runtime.routing import DirectorEngineRouter
from app.director.runtime.wakeups import (
    DirectorRuntimeWakeupService,
    process_runtime_wakeup,
)
from app.director.turn_service import DirectorTurnService
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError, ValidationAppError
from psycopg import errors
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    DB_PASSWORD,
    DB_USER,
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
    _host,
    _port,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_langgraph_director_runtime import (
    FakeResumeClaims,
    FakeRuntimeTools,
    _request,
)
from tests.unit.test_workbench_execution import _seed

CHECKPOINT_ROLE = "dramaforge_director_checkpoint"
CHECKPOINT_PASSWORD = "d5-checkpoint-test-password"


@pytest.fixture(scope="module")
def event_loop_policy():
    if os.name == "nt":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


def _admin_dsn(dbname: str) -> str:
    return f"postgresql://{DB_USER}:{DB_PASSWORD}@{_host()}:{_port()}/{dbname}"


def _checkpoint_dsn(dbname: str) -> str:
    return (
        f"postgresql://{CHECKPOINT_ROLE}:{CHECKPOINT_PASSWORD}"
        f"@{_host()}:{_port()}/{dbname}"
    )


@pytest.mark.asyncio
async def test_migrated_checkpoint_schema_is_compatible_and_project_scoped():
    dbname = f"dramaforge_d5_checkpoint_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin_dsn = _admin_dsn(dbname)
    try:
        _alembic(dbname)
        async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
            await admin.execute(
                f"ALTER ROLE {CHECKPOINT_ROLE} LOGIN PASSWORD '{CHECKPOINT_PASSWORD}'"
            )

        project_a = uuid4()
        project_b = uuid4()
        scope_a = RuntimeScope(
            workspace_id=uuid4(), project_id=project_a, actor_id=uuid4(),
        )
        scope_b = RuntimeScope(
            workspace_id=uuid4(), project_id=project_b, actor_id=uuid4(),
        )
        turn_id = uuid4()
        settings = Settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url=_checkpoint_dsn(dbname),
        )

        tools_a = FakeRuntimeTools(project_id=project_a)
        async with scoped_checkpointer(settings, project_id=project_a) as saver_a:
            runtime_a = LangGraphDirectorRuntime(
                checkpointer=saver_a,
                tools=tools_a,
                resume_claims=FakeResumeClaims(),
            )
            waiting_a = await runtime_a.start(_request(scope_a, turn_id))
            assert waiting_a.status == "awaiting_user"

        dsn_a = scoped_checkpoint_dsn(_checkpoint_dsn(dbname), project_id=project_a)
        dsn_b = scoped_checkpoint_dsn(_checkpoint_dsn(dbname), project_id=project_b)
        async with await psycopg.AsyncConnection.connect(dsn_a) as connection:
            count_a = await (await connection.execute(
                "SELECT count(*) FROM checkpoints"
            )).fetchone()
            assert count_a is not None and count_a[0] > 0
        async with await psycopg.AsyncConnection.connect(dsn_b) as connection:
            count_b = await (await connection.execute(
                "SELECT count(*) FROM checkpoints"
            )).fetchone()
            assert count_b == (0,)

        tools_b = FakeRuntimeTools(project_id=project_b)
        async with scoped_checkpointer(settings, project_id=project_b) as saver_b:
            isolated_b = LangGraphDirectorRuntime(
                checkpointer=saver_b,
                tools=tools_b,
                resume_claims=FakeResumeClaims(),
            )
            with pytest.raises(NotFoundError):
                await isolated_b.read(scope=scope_a, turn_id=turn_id)
            waiting_b = await isolated_b.start(_request(scope_b, turn_id))
            assert waiting_b.status == "awaiting_user"

        async with scoped_checkpointer(settings, project_id=project_a) as saver_a:
            reconnected_a = LangGraphDirectorRuntime(
                checkpointer=saver_a,
                tools=tools_a,
                resume_claims=FakeResumeClaims(),
            )
            assert await reconnected_a.read(scope=scope_a, turn_id=turn_id) == waiting_a
            with pytest.raises(NotFoundError):
                await reconnected_a.read(scope=scope_b, turn_id=turn_id)

        async with await psycopg.AsyncConnection.connect(admin_dsn) as app_connection:
            await app_connection.execute("SET ROLE dramaforge_app")
            with pytest.raises(errors.InsufficientPrivilege):
                await app_connection.execute(
                    "SELECT count(*) FROM director_runtime_checkpoints.checkpoints"
                )
    finally:
        try:
            async with await psycopg.AsyncConnection.connect(
                admin_dsn, autocommit=True,
            ) as admin:
                await admin.execute(
                    f"ALTER ROLE {CHECKPOINT_ROLE} NOLOGIN PASSWORD NULL"
                )
        finally:
            await _drop_database(dbname)


@pytest.mark.asyncio
async def test_executor_recovers_committed_signal_and_projects_once():
    dbname = f"dramaforge_d5_executor_{uuid4().hex[:8]}"
    await _create_database(dbname)
    admin_dsn = _admin_dsn(dbname)
    admin_engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
            await admin.execute(
                f"ALTER ROLE {CHECKPOINT_ROLE} LOGIN PASSWORD '{CHECKPOINT_PASSWORD}'"
            )
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin_factory() as session:
            project, _binding, actor = await _seed(session)
            await session.commit()
        scope = RuntimeScope(
            workspace_id=project.workspace_id,
            project_id=project.id,
            actor_id=actor.id,
        )
        settings = Settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url=_checkpoint_dsn(dbname),
        )
        tools = FakeRuntimeTools(project_id=project.id)

        async with app_factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            thread = DirectorThread(
                project_id=project.id,
                scope_type="project",
                scope_entity_id=project.id,
                title="D5 executor",
                created_by=actor.id,
            )
            session.add(thread)
            await session.flush()
            session.add(DirectorProposal(
                id=tools.proposal_id,
                project_id=project.id,
                thread_id=thread.id,
                scope_type="project",
                scope_entity_id=project.id,
                created_by=actor.id,
            ))
            turn, created = await DirectorTurnService(session).create_or_get(
                project=project,
                actor=actor,
                scope_type="project",
                scope_entity_id=project.id,
                request_key="d5:executor",
                context_snapshot={"goal": "bounded runtime"},
                intent_snapshot={"task": "test"},
                max_steps=6,
            )
            control = await DirectorEngineRouter(
                settings=settings,
                controls=DirectorRuntimeControlService(session),
            ).bind_new(turn, created=created)
            assert control is not None
            execution_id = control.runtime_execution_id
            request = RuntimeInput(
                scope=scope,
                turn_id=turn.id,
                runtime_execution_id=execution_id,
                engine_version=control.engine_version,
                input_reference=project.id,
                max_steps=6,
            )
            wakeup = await DirectorRuntimeWakeupService(session).enqueue_start(request)
            await session.commit()

        assert await process_runtime_wakeup(
            app_factory,
            wakeup_id=wakeup.id,
            executor_factory=lambda session, _wakeup: DirectorRuntimeExecutor(
                session, settings=settings, tools=tools, worker_id="worker-start",
            ),
        )
        async with app_factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            stored = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert stored.status == "awaiting_user"
            waiting_revision = stored.runtime_revision
            assert waiting_revision is not None
            projected_revision = stored.revision

        decision_id = uuid4()
        tools.decisions[decision_id] = "accept"
        signal = ResumeSignal(
            scope=scope,
            turn_id=turn.id,
            signal_id=uuid4(),
            reason="user_decision",
            reference_id=decision_id,
            expected_revision=waiting_revision,
        )
        async with app_factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            controls = DirectorRuntimeControlService(session)
            crashed = await controls.claim(
                project_id=project.id,
                runtime_execution_id=execution_id,
                worker_id="worker-crashed",
            )
            assert await controls.claim_signal(signal=signal, lease=crashed)
            await session.commit()
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            await session.execute(
                update(DirectorRuntimeControl)
                .where(DirectorRuntimeControl.runtime_execution_id == execution_id)
                .values(lease_expires_at=datetime(2000, 1, 1, tzinfo=UTC))
            )
            await session.commit()

        async with app_factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            submitted = await DirectorRuntimeExecutor(
                session, settings=settings, tools=tools, worker_id="worker-recovery",
            ).resume(signal=signal, runtime_execution_id=execution_id)
            assert submitted.status == "awaiting_execution"
            assert tools.production_creates == 1
            stored = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert stored.runtime_revision == submitted.revision
            submitted_projection_revision = stored.revision
            assert submitted_projection_revision > projected_revision

        async with app_factory() as session:
            await set_rls_context(
                session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            replay = await DirectorRuntimeExecutor(
                session, settings=settings, tools=tools, worker_id="worker-replay",
            ).resume(signal=signal, runtime_execution_id=execution_id)
            assert replay == submitted
            stored = await DirectorTurnService(session).get(
                project_id=project.id, turn_id=turn.id,
            )
            assert stored.revision == submitted_projection_revision
            assert tools.production_creates == 1
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()
        try:
            async with await psycopg.AsyncConnection.connect(
                admin_dsn, autocommit=True,
            ) as admin:
                await admin.execute(
                    f"ALTER ROLE {CHECKPOINT_ROLE} NOLOGIN PASSWORD NULL"
                )
        finally:
            await _drop_database(dbname)


def test_checkpoint_dsn_rejects_unscoped_or_caller_owned_options():
    with pytest.raises(ValidationAppError):
        scoped_checkpoint_dsn("", project_id=uuid4())
    with pytest.raises(ValidationAppError) as forbidden:
        scoped_checkpoint_dsn(
            "postgresql://user:pass@localhost/db?options=-c%20search_path%3Dpublic",
            project_id=uuid4(),
        )
    assert forbidden.value.details["code"] == "DIRECTOR_CHECKPOINT_OPTIONS_FORBIDDEN"
