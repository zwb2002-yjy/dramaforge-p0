"""D5 real PostgreSQL engine binding, RLS, lease fencing and signal claims."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.contracts.director_runtime import ResumeSignal, RuntimeScope
from app.director.runtime.control import DirectorRuntimeControlService
from app.director.runtime.langgraph_adapter import ENGINE_VERSION, STATE_SCHEMA_VERSION
from app.director.runtime.models import DirectorRuntimeControl
from app.director.turn_models import DirectorTurn
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, NotFoundError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _seed


@pytest.mark.asyncio
async def test_engine_binding_fencing_signal_claims_and_project_rls():
    dbname = f"dramaforge_d5_control_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    try:
        _alembic(dbname)
        admin = async_sessionmaker(engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin() as session:
            project, _binding, actor = await _seed(session)
            other, _other_binding, other_actor = await _seed(session)
            turn = DirectorTurn(
                project_id=project.id,
                workspace_id=project.workspace_id,
                actor_id=actor.id,
                scope_type="shot",
                scope_entity_id=uuid4(),
                request_key="d5:bound",
                context_hash="c" * 64,
            )
            legacy = DirectorTurn(
                project_id=project.id,
                workspace_id=project.workspace_id,
                actor_id=actor.id,
                scope_type="shot",
                scope_entity_id=uuid4(),
                request_key="d5:legacy",
                context_hash="d" * 64,
            )
            session.add_all([turn, legacy])
            await session.commit()

        async def scope(session, *, foreign: bool = False):
            selected_project = other if foreign else project
            selected_actor = other_actor if foreign else actor
            await set_rls_context(
                session,
                user_id=selected_actor.id,
                workspace_id=selected_project.workspace_id,
                project_id=selected_project.id,
            )

        async with factory() as session:
            await scope(session)
            stored_legacy = await session.get(DirectorTurn, legacy.id)
            assert stored_legacy is not None
            assert stored_legacy.engine_version is None
            assert stored_legacy.runtime_execution_id is None

            service = DirectorRuntimeControlService(session)
            control = await service.bind(
                project_id=project.id,
                turn_id=turn.id,
                engine_version=ENGINE_VERSION,
                state_schema_version=STATE_SCHEMA_VERSION,
            )
            execution_id = control.runtime_execution_id
            await session.commit()
            await scope(session)
            replay = await service.bind(
                project_id=project.id,
                turn_id=turn.id,
                engine_version=ENGINE_VERSION,
                state_schema_version=STATE_SCHEMA_VERSION,
            )
            assert replay.runtime_execution_id == execution_id
            with pytest.raises(ConflictError):
                await service.bind(
                    project_id=project.id,
                    turn_id=turn.id,
                    engine_version="legacy:changed",
                    state_schema_version=STATE_SCHEMA_VERSION,
                )
            await session.rollback()

            await scope(session)
            lease_one = await service.claim(
                project_id=project.id,
                runtime_execution_id=execution_id,
                worker_id="worker-one",
            )
            await session.commit()
            await scope(session)
            with pytest.raises(ConflictError) as held:
                await service.claim(
                    project_id=project.id,
                    runtime_execution_id=execution_id,
                    worker_id="worker-two",
                )
            assert held.value.details["code"] == "DIRECTOR_RUNTIME_LEASE_HELD"
            await session.rollback()

            await scope(session)
            await session.execute(
                update(DirectorRuntimeControl).where(
                    DirectorRuntimeControl.runtime_execution_id == execution_id,
                ).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
            await scope(session)
            lease_two = await service.claim(
                project_id=project.id,
                runtime_execution_id=execution_id,
                worker_id="worker-two",
            )
            assert lease_two.epoch == lease_one.epoch + 1
            await session.commit()

            await scope(session)
            with pytest.raises(ConflictError) as stale:
                async with service.guard(lease_one):
                    pass
            assert stale.value.details["code"] == "DIRECTOR_RUNTIME_LEASE_STALE"
            await session.rollback()

            await scope(session)
            signal_id = uuid4()
            signal = ResumeSignal(
                scope=RuntimeScope(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    actor_id=actor.id,
                ),
                turn_id=turn.id,
                signal_id=signal_id,
                reason="user_decision",
                reference_id=uuid4(),
                expected_revision=2,
            )
            assert await service.claim_signal(signal=signal, lease=lease_two)
            assert not await service.claim_signal(signal=signal, lease=lease_two)
            changed = signal.model_copy(update={"reference_id": uuid4()})
            with pytest.raises(ConflictError):
                await service.claim_signal(signal=changed, lease=lease_two)
            await session.commit()

            await scope(session)
            await service.release_waiting(lease_two)
            await session.commit()

            await scope(session)
            assert await service.mark_project_stale(project_id=project.id) == 1
            await session.commit()
            await scope(session)
            with pytest.raises(ConflictError) as invalidated:
                await service.claim(
                    project_id=project.id,
                    runtime_execution_id=execution_id,
                    worker_id="worker-three",
                )
            assert invalidated.value.details["code"] == "DIRECTOR_RUNTIME_STOPPED"
            await session.rollback()

        async with factory() as session:
            await scope(session, foreign=True)
            assert await session.scalar(select(DirectorRuntimeControl)) is None
            with pytest.raises(NotFoundError):
                await DirectorRuntimeControlService(session).claim(
                    project_id=project.id,
                    runtime_execution_id=execution_id,
                    worker_id="foreign-worker",
                )
            await session.rollback()

        async with factory() as session:
            await scope(session)
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(DirectorTurn).where(DirectorTurn.id == legacy.id).values(
                        engine_version=ENGINE_VERSION,
                    )
                )
                await session.flush()
            await session.rollback()
    finally:
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)
