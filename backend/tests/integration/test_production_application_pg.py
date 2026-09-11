"""Shared application acceptance with real locks, replay and no director rows."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.access.models import ProjectCreativeProfile, User
from app.assets.models import Shot
from app.contracts.production_commands import ExecutionBody
from app.director.turn_models import DirectorTurn
from app.events.models import EventLog, OutboxEvent
from app.execution.models import NodeRun, ProviderOperation
from app.production.application.authorization import ProductionAuthorizations
from app.production.application.commands import ProductionCommands
from app.production.command_models import ProductionCommandAuthorization
from app.production.workbench_execution import WorkbenchExecutionService
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    BACKEND,
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _input, _seed, _seed_video_shot


@pytest.mark.asyncio
async def test_application_duplicate_acceptance_needs_no_director(monkeypatch):
    dbname = f"dramaforge_d1_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            project, binding, actor = await _seed(session)
            shot, _artifact = await _seed_video_shot(session, project=project, user=actor)
            await session.commit()
            command = _input(
                project_id=project.id, shot_id=shot.id,
                requested_binding_id=binding.id, expected_shot_version=shot.version,
            )
            plan = await WorkbenchExecutionService(session, user_id=actor.id).build_plan(
                project=project, execution_input=command,
            )
            body = ExecutionBody(
                **command.model_dump(exclude={"project_id", "shot_id", "shot_experiment_id"}),
                plan_fingerprint=plan.plan_fingerprint,
                accepted_approximations=plan.accepted_approximations,
            )
            project_id, workspace_id, actor_id, shot_id = (
                project.id, project.workspace_id, actor.id, shot.id,
            )
        original_lock = WorkbenchExecutionService.lock_command_scope
        arrived = 0
        barrier = asyncio.Event()

        async def synchronized_lock(self, *, project_id):
            nonlocal arrived
            arrived += 1
            if arrived >= 2:
                barrier.set()
            await asyncio.wait_for(barrier.wait(), 10)
            await original_lock(self, project_id=project_id)

        monkeypatch.setattr(WorkbenchExecutionService, "lock_command_scope", synchronized_lock)

        async def submit(payload):
            async with factory() as session:
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(
                    session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id,
                )
                actor = await session.get(User, actor_id)
                receipt = await ProductionCommands(session).submit_user_execution(
                    actor=actor, project_id=project_id, shot_id=shot_id,
                    body=payload, command_key="d1-same-command",
                )
                await session.commit()
                return receipt

        receipts = await asyncio.gather(submit(body), submit(body))
        assert receipts[0] == receipts[1]
        async with factory() as session:
            notices = list((await session.scalars(select(OutboxEvent).where(
                OutboxEvent.topic == "production.facts.v1",
            ))).all())
            assert len(notices) == 1
            assert notices[0].payload["notice"]["node_run_id"] == str(receipts[0].node_run_id)
            baseline_runs = set((await session.scalars(select(NodeRun.id))).all())
            actor = await session.get(User, actor_id)
            rolled_back = await ProductionCommands(session).submit_user_execution(
                actor=actor, project_id=project_id, shot_id=shot_id,
                body=body, command_key="rollback-before-commit",
            )
            assert rolled_back.node_run_id not in baseline_runs
            await session.rollback()
        async with factory() as session:
            assert set((await session.scalars(select(NodeRun.id))).all()) == baseline_runs
            assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.topic == "production.facts.v1",
            )) == 1
            assert await session.scalar(select(func.count()).select_from(EventLog).where(
                EventLog.event_type == "execution_accepted",
            )) == 1
        with pytest.raises(ConflictError) as conflict:
            await submit(body.model_copy(update={"prompt": "different input"}))
        assert conflict.value.details["code"] == "EXECUTION_COMMAND_REUSED"
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(DirectorTurn)) == 0
            assert await session.scalar(select(func.count()).select_from(ProviderOperation)) == 0
            session.add(ProjectCreativeProfile(
                project_id=project_id, start_type="FREE", director_autonomy="AUTO",
            ))
            await session.commit()
        async with factory() as session:
            actor = await session.get(User, actor_id)
            grants = ProductionAuthorizations(session)
            decision_id = uuid4()
            expiry = datetime.now(UTC) + timedelta(hours=1)
            approved = await grants.approve_user_action(
                actor=actor, project_id=project_id, shot_id=shot_id,
                decision_id=decision_id, body=body, expires_at=expiry,
            )
            assert await grants.approve_user_action(
                actor=actor, project_id=project_id, shot_id=shot_id,
                decision_id=decision_id, body=body, expires_at=expiry,
            ) == approved
            with pytest.raises(ConflictError) as changed_decision:
                await grants.approve_user_action(
                    actor=actor, project_id=project_id, shot_id=shot_id,
                    decision_id=decision_id, body=body.model_copy(update={"prompt": "changed"}),
                    expires_at=expiry,
                )
            assert changed_decision.value.details["code"] == "PRODUCTION_DECISION_REUSED"
            revoked = await grants.approve_user_action(
                actor=actor, project_id=project_id, shot_id=shot_id,
                decision_id=uuid4(),
                body=body, expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            mode_pending = await grants.approve_user_action(
                actor=actor, project_id=project_id, shot_id=shot_id,
                decision_id=uuid4(), body=body, expires_at=expiry,
            )
            await session.commit()
        submitting_pids = {}
        async def submit_grant(grant_id):
            async with factory() as session:
                submitting_pids[grant_id] = await session.scalar(text("SELECT pg_backend_pid()"))
                await session.execute(text("SET LOCAL ROLE dramaforge_app"))
                await set_rls_context(
                    session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id,
                )
                actor = await session.get(User, actor_id)
                result = await ProductionAuthorizations(session).submit(
                    actor=actor, project_id=project_id, authorization_id=grant_id,
                )
                await session.commit()
                return result
        accepted = await asyncio.gather(submit_grant(approved), submit_grant(approved))
        assert accepted[0] == accepted[1]
        async with factory() as session:
            actor = await session.get(User, actor_id)
            await ProductionAuthorizations(session).revoke(
                actor=actor, project_id=project_id, authorization_id=revoked,
            )
            # Hold the revocation transaction open and prove submission is
            # waiting on its PostgreSQL lock before allowing revoke to commit.
            blocked_submit = asyncio.create_task(submit_grant(revoked))
            try:
                async with factory() as observer:
                    blockers = []
                    for _ in range(200):
                        pid = submitting_pids.get(revoked)
                        if pid is not None:
                            blockers = await observer.scalar(
                                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
                            )
                            if blockers:
                                break
                        await asyncio.sleep(0.01)
                    assert blockers, "submission did not serialize behind revocation"
                await session.commit()
                with pytest.raises(ConflictError) as raced:
                    await asyncio.wait_for(blocked_submit, 10)
                assert raced.value.details["code"] == "PRODUCTION_AUTHORIZATION_INVALID"
            finally:
                if not blocked_submit.done():
                    blocked_submit.cancel()
                    await asyncio.gather(blocked_submit, return_exceptions=True)
        with pytest.raises(ConflictError) as denied:
            await submit_grant(revoked)
        assert denied.value.details["code"] == "PRODUCTION_AUTHORIZATION_INVALID"
        async with factory() as session:
            await session.execute(update(ProjectCreativeProfile).where(
                ProjectCreativeProfile.project_id == project_id,
            ).values(director_autonomy="MANUAL", version=2))
            await session.commit()
        with pytest.raises(ConflictError) as manual:
            await submit_grant(mode_pending)
        assert manual.value.details["code"] == "PRODUCTION_AUTHORIZATION_INVALID"
        assert await submit_grant(approved) == accepted[0]
        # Switching back to AUTO cannot reactivate a grant from an older profile.
        async with factory() as session:
            await session.execute(update(ProjectCreativeProfile).where(
                ProjectCreativeProfile.project_id == project_id,
            ).values(director_autonomy="AUTO", version=3))
            await session.commit()
        with pytest.raises(ConflictError):
            await submit_grant(mode_pending)
        # A caller may have cached the Shot before waiting on another writer.
        # Acceptance must refresh that object under its lock, rather than using
        # the identity map's obsolete version and approving a stale plan.
        async with factory() as stale_session:
            actor = await stale_session.get(User, actor_id)
            cached_shot = await stale_session.get(Shot, shot_id)
            assert cached_shot.version == body.expected_shot_version
            async with factory() as editor:
                await editor.execute(
                    update(Shot).where(Shot.id == shot_id).values(version=shot.version + 1),
                )
                await editor.commit()
            with pytest.raises(ValidationAppError) as stale:
                await ProductionCommands(stale_session).submit_user_execution(
                    actor=actor, project_id=project_id, shot_id=shot_id,
                    body=body, command_key="new-command-after-edit",
                )
            assert stale.value.details["code"] == "SHOT_VERSION_MISMATCH"
        # Replaying the already accepted command is still a receipt lookup.
        assert await submit(body) == receipts[0]
    finally:
        await engine.dispose()
        await _drop_database(dbname)


@pytest.mark.asyncio
async def test_authorization_migration_upgrade_downgrade_preserves_production_tables():
    dbname = f"dramaforge_d1_migration_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        async with engine.connect() as connection:
            table = await connection.scalar(text(
                "SELECT to_regclass('public.production_command_authorizations')"
            ))
            assert table is not None
            assert await connection.scalar(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE oid = 'production_command_authorizations'::regclass"
            ))
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "20260908_0060"],
            cwd=BACKEND, env={**os.environ, "DATABASE_URL": _async_url(dbname)},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        async with engine.connect() as connection:
            assert await connection.scalar(text(
                "SELECT to_regclass('public.production_command_authorizations')"
            )) is None
            assert await connection.scalar(text("SELECT to_regclass('public.node_runs')"))
        _alembic(dbname)
    finally:
        await engine.dispose()
        await _drop_database(dbname)


@pytest.mark.asyncio
async def test_expired_grant_and_cross_project_rls_cannot_create_production():
    dbname = f"dramaforge_d1_scope_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            project, binding, actor = await _seed(session)
            shot, _artifact = await _seed_video_shot(session, project=project, user=actor)
            session.add(ProjectCreativeProfile(
                project_id=project.id, start_type="FREE", director_autonomy="AUTO",
            ))
            other, _binding, other_actor = await _seed(session)
            session.add(ProjectCreativeProfile(
                project_id=other.id, start_type="FREE", director_autonomy="AUTO",
            ))
            await session.commit()
            body = ExecutionBody(
                stage="video", prompt="Test expiry before any plan resolution",
                mode_id="image_to_video", expected_shot_version=shot.version,
                requested_binding_id=binding.id, plan_fingerprint="a" * 64,
            )
            grant_id = await ProductionAuthorizations(session).approve_user_action(
                actor=actor, project_id=project.id, shot_id=shot.id, decision_id=uuid4(),
                body=body, expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            await session.commit()
            await session.execute(update(ProductionCommandAuthorization).where(
                ProductionCommandAuthorization.id == grant_id,
            ).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
            await session.commit()
            owner_scope = (actor.id, project.workspace_id, project.id)
            other_scope = (other_actor.id, other.workspace_id, other.id)
            baseline_runs = set((await session.scalars(select(NodeRun.id))).all())

        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(session, user_id=owner_scope[0], workspace_id=owner_scope[1],
                                  project_id=owner_scope[2])
            owner = await session.get(User, owner_scope[0])
            with pytest.raises(ConflictError) as expired:
                await ProductionAuthorizations(session).submit(
                    actor=owner, project_id=owner_scope[2], authorization_id=grant_id,
                )
            assert expired.value.details["code"] == "PRODUCTION_AUTHORIZATION_INVALID"
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(session, user_id=other_scope[0], workspace_id=other_scope[1],
                                  project_id=other_scope[2])
            assert await session.get(ProductionCommandAuthorization, grant_id) is None
            modified = await session.execute(update(ProductionCommandAuthorization).where(
                ProductionCommandAuthorization.id == grant_id,
            ).values(status="revoked"))
            assert modified.rowcount == 0
            other_user = await session.get(User, other_scope[0])
            with pytest.raises(NotFoundError):
                await ProductionAuthorizations(session).submit(
                    actor=other_user, project_id=other_scope[2], authorization_id=grant_id,
                )
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(ProviderOperation)) == 0
            assert set((await session.scalars(select(NodeRun.id))).all()) == baseline_runs
    finally:
        await engine.dispose()
        await _drop_database(dbname)
