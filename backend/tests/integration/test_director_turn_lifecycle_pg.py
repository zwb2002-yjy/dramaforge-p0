"""R4a PostgreSQL proof for one-winner DirectorTurn claim semantics."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from app.director.turn_service import DirectorTurnService
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from pg_support import env_target
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
DB_USER = os.environ.get("TEST_PG_USER", "dramaforge")
DB_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "dramaforge")


def _host() -> str:
    return env_target()[0]


def _port() -> str:
    return env_target()[1]


def _admin_url() -> str:
    return os.environ.get(
        "TEST_PG_ADMIN_URL",
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{_host()}:{_port()}/postgres",
    )


def _sync_url(dbname: str) -> str:
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{_host()}:{_port()}/{dbname}"


def _async_url(dbname: str) -> str:
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{_host()}:{_port()}/{dbname}"


def _pg_available() -> bool:
    try:
        engine = create_engine(_sync_url("dramaforge"), connect_args={"connect_timeout": 2})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _pg_available(),
    reason="requires the explicitly configured isolated PostgreSQL quality target",
)


async def _create_database(name: str) -> None:
    connection = await asyncpg.connect(_admin_url())
    try:
        await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


async def _drop_database(name: str) -> None:
    connection = await asyncpg.connect(_admin_url())
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await connection.close()


def _alembic(dbname: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = _async_url(dbname)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_only_one_postgres_worker_claims_and_restart_recovery_is_fail_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dbname = f"dramaforge_turn_claim_{uuid.uuid4().hex[:8]}"
    try:
        await _create_database(dbname)
        _alembic(dbname)
        ids = {
            key: uuid.uuid4()
            for key in (
                "user",
                "workspace",
                "project",
                "scope",
                "turn",
                "stale_turn",
                "graph",
                "graph_version",
                "graph_node",
                "node_run",
                "waiting_turn",
            )
        }
        sync_engine = create_engine(_sync_url(dbname))
        with sync_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id,email,display_name,password_hash) "
                    "VALUES (:id,:email,'Director','x')"
                ),
                {"id": ids["user"], "email": f"turn-claim-{uuid.uuid4().hex}@example.com"},
            )
            connection.execute(
                text(
                    "INSERT INTO workspaces (id,owner_user_id,name) "
                    "VALUES (:id,:owner,'Turn claim WS')"
                ),
                {"id": ids["workspace"], "owner": ids["user"]},
            )
            connection.execute(
                text(
                    "INSERT INTO projects (id,workspace_id,name,aspect_ratio,budget_limit) "
                    "VALUES (:id,:workspace,'Turn claim project','9:16',0)"
                ),
                {"id": ids["project"], "workspace": ids["workspace"]},
            )
            connection.execute(
                text(
                    "INSERT INTO director_turns "
                    "(id,workspace_id,project_id,actor_id,scope_type,scope_entity_id,"
                    "request_key,context_hash,request_summary,status,revision,step_count) "
                    "VALUES (:id,:workspace,:project,:actor,'shot',:scope,"
                    "'claim-once',:hash,CAST(:summary AS jsonb),'queued',1,0)"
                ),
                {
                    "id": ids["turn"],
                    "workspace": ids["workspace"],
                    "project": ids["project"],
                    "actor": ids["user"],
                    "scope": ids["scope"],
                    "hash": "a" * 64,
                    "summary": '{"max_steps": 2}',
                },
            )
            connection.execute(
                text(
                    "INSERT INTO production_graphs "
                    "(id,project_id,scope_type,scope_entity_id,template_key,status,"
                    "created_by,version) VALUES "
                    "(:id,:project,'shot',:scope,'shot-p0-v1','published',:actor,1)"
                ),
                {
                    "id": ids["graph"],
                    "project": ids["project"],
                    "scope": ids["scope"],
                    "actor": ids["user"],
                },
            )
            connection.execute(
                text(
                    "INSERT INTO graph_versions "
                    "(id,graph_id,version_number,status,definition_hash,definition) "
                    "VALUES (:id,:graph,1,'published',:hash,CAST('{}' AS jsonb))"
                ),
                {
                    "id": ids["graph_version"],
                    "graph": ids["graph"],
                    "hash": "c" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO graph_nodes "
                    "(id,graph_version_id,node_key,node_type,display_name,input_schema,"
                    "output_schema,config,cacheable) VALUES "
                    "(:id,:version,'keyframe','keyframe','Keyframe',CAST('{}' AS jsonb),"
                    "CAST('{}' AS jsonb),CAST('{}' AS jsonb),true)"
                ),
                {"id": ids["graph_node"], "version": ids["graph_version"]},
            )
            connection.execute(
                text(
                    "INSERT INTO node_runs "
                    "(id,project_id,graph_version_id,graph_node_id,attempt_no,idempotency_key,"
                    "input_hash,status,input_snapshot,output_summary,created_by) VALUES "
                    "(:id,:project,:version,:node,1,'director-next-action',:hash,'running',"
                    "CAST('{}' AS jsonb),CAST('{}' AS jsonb),:actor)"
                ),
                {
                    "id": ids["node_run"],
                    "project": ids["project"],
                    "version": ids["graph_version"],
                    "node": ids["graph_node"],
                    "hash": "d" * 64,
                    "actor": ids["user"],
                },
            )
            connection.execute(
                text(
                    "INSERT INTO director_turns "
                    "(id,workspace_id,project_id,actor_id,scope_type,scope_entity_id,"
                    "request_key,context_hash,request_summary,status,wait_reason,node_run_ids,"
                    "revision,step_count) VALUES "
                    "(:id,:workspace,:project,:actor,'shot',:scope,'waiting-execution',:hash,"
                    "CAST(:summary AS jsonb),'awaiting_execution','execution',"
                    "CAST(:runs AS jsonb),1,1)"
                ),
                {
                    "id": ids["waiting_turn"],
                    "workspace": ids["workspace"],
                    "project": ids["project"],
                    "actor": ids["user"],
                    "scope": ids["scope"],
                    "hash": "e" * 64,
                    "summary": '{"max_steps": 4}',
                    "runs": f'["{ids["node_run"]}"]',
                },
            )
            connection.execute(
                text(
                    "INSERT INTO director_turns "
                    "(id,workspace_id,project_id,actor_id,scope_type,scope_entity_id,"
                    "request_key,context_hash,request_summary,status,transport_status,"
                    "revision,step_count,updated_at) "
                    "VALUES (:id,:workspace,:project,:actor,'shot',:scope,"
                    "'interrupted-once',:hash,CAST(:summary AS jsonb),'thinking',"
                    "'submission_started',1,1,now() - interval '20 minutes')"
                ),
                {
                    "id": ids["stale_turn"],
                    "workspace": ids["workspace"],
                    "project": ids["project"],
                    "actor": ids["user"],
                    "scope": ids["scope"],
                    "hash": "b" * 64,
                    "summary": '{"max_steps": 2}',
                },
            )
        sync_engine.dispose()

        engine = create_async_engine(_async_url(dbname))
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def claim() -> str:
            async with factory() as session:
                await set_rls_context(
                    session,
                    user_id=ids["user"],
                    workspace_id=ids["workspace"],
                    project_id=ids["project"],
                )
                try:
                    turn = await DirectorTurnService(session).claim(
                        project_id=ids["project"],
                        turn_id=ids["turn"],
                        expected_revision=1,
                    )
                    await session.commit()
                    return f"claimed:{turn.revision}"
                except ConflictError as exc:
                    await session.rollback()
                    return str(exc.details["code"])

        outcomes = await asyncio.gather(claim(), claim())
        assert sorted(outcomes) == ["DIRECTOR_TURN_CLAIM_CONFLICT", "claimed:2"]

        from app.access.models import Project
        from app.director.next_action import DirectorNextActionService

        # Force both workers to derive from the same pre-CAS revision, rather
        # than accidentally testing two sequential reads on a fast database.
        ready = asyncio.Event()
        arrivals = 0
        original_cas = DirectorTurnService.compare_and_set

        async def racing_cas(self, **kwargs):
            nonlocal arrivals
            if kwargs.get("increment_step"):
                arrivals += 1
                if arrivals == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=10)
            return await original_cas(self, **kwargs)

        monkeypatch.setattr(DirectorTurnService, "compare_and_set", racing_cas)

        async def reconcile(event_key: str) -> str:
            async with factory() as session:
                await set_rls_context(
                    session,
                    user_id=ids["user"],
                    workspace_id=ids["workspace"],
                    project_id=ids["project"],
                )
                project = await session.get(Project, ids["project"])
                assert project is not None
                result = await DirectorNextActionService(session).reconcile(
                    project=project,
                    turn_id=ids["waiting_turn"],
                    event_key=event_key,
                )
                await session.commit()
                return str(result.action)

        reconciliations = await asyncio.gather(reconcile("worker:a"), reconcile("worker:b"))
        assert reconciliations == ["wait_for_execution", "wait_for_execution"]
        monkeypatch.setattr(DirectorTurnService, "compare_and_set", original_cas)

        from app.director.turn_models import DirectorTurn
        from app.workers import jobs

        monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
        startup_ctx = {"job_id": "restart-proof"}
        recovery = await jobs.recover_interrupted_director_turns(startup_ctx)
        assert startup_ctx["director_scan_state"] == {"cursor": None}
        assert recovery == {"recovered": 1, "unchanged": 0}
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["user"],
                workspace_id=ids["workspace"],
                project_id=ids["project"],
            )
            stale = await session.get(DirectorTurn, ids["stale_turn"])
            assert stale is not None
            assert stale.status == "failed"
            assert stale.wait_reason == "text_submission_unknown"

        from app.execution.models import Artifact, NodeRun

        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["user"],
                workspace_id=ids["workspace"],
                project_id=ids["project"],
            )
            artifact = Artifact(
                project_id=ids["project"],
                artifact_type="image",
                storage_state="available",
                object_key=f"obj/{uuid.uuid4().hex}",
                content_hash="f" * 64,
                mime_type="image/png",
                byte_size=1,
            )
            session.add(artifact)
            await session.flush()
            run = await session.get(NodeRun, ids["node_run"])
            assert run is not None
            run.status = "completed"
            run.result_artifact_id = artifact.id
            await session.commit()

        scan = await jobs.reconcile_waiting_director_turns({"job_id": "closed-browser"})
        assert scan == {"reconciled": 1, "unchanged": 0, "failed": 0}
        repeated_scan = await jobs.reconcile_waiting_director_turns(
            {"job_id": "closed-browser-repeat"}
        )
        assert repeated_scan == {"reconciled": 0, "unchanged": 0, "failed": 0}
        async with factory() as session:
            await set_rls_context(
                session,
                user_id=ids["user"],
                workspace_id=ids["workspace"],
                project_id=ids["project"],
            )
            waiting = await session.get(DirectorTurn, ids["waiting_turn"])
            assert waiting is not None
            assert waiting.status == "awaiting_user"
            assert waiting.wait_reason == "production_review"
            assert waiting.step_count == 3
            assert waiting.revision == 3
            assert len(waiting.response_summary["coordination"]["processed_events"]) == 2
            project = await session.get(Project, ids["project"])
            reopened = await DirectorNextActionService(session).reconcile(
                project=project, turn_id=waiting.id,
            )
            assert reopened.action == "review_production_result"
            assert waiting.revision == 3
        # R4c1 JSON decision guards and mode invalidation survive transaction
        # boundaries on real PostgreSQL, while submitted media stays terminal.
        decision_id = uuid.uuid4()
        async with factory() as session:
            await set_rls_context(session, user_id=ids["user"], workspace_id=ids["workspace"],
                                  project_id=ids["project"])
            session.add(DirectorTurn(
                id=decision_id, workspace_id=ids["workspace"], project_id=ids["project"],
                actor_id=ids["user"], scope_type="shot", scope_entity_id=ids["scope"],
                request_key="decision:pg", context_hash="a" * 64,
                request_summary={"task": "shot_director_suggestion", "max_steps": 4},
                output_snapshot={"suggested_director_state": {}}, output_hash="b" * 64,
                status="awaiting_user", step_count=1,
            ))
            await session.commit()
        async with factory() as session:
            await set_rls_context(session, user_id=ids["user"], workspace_id=ids["workspace"],
                                  project_id=ids["project"])
            await DirectorTurnService(session).record_user_decision(
                project_id=ids["project"], turn_id=decision_id, expected_revision=1,
                decision="reject", accepted_operation_indices=[],
            )
            await session.commit()
        async with factory() as session:
            await set_rls_context(session, user_id=ids["user"], workspace_id=ids["workspace"],
                                  project_id=ids["project"])
            with pytest.raises(ConflictError) as rejection:
                await DirectorTurnService(session).assert_context_not_rejected(
                    project_id=ids["project"], context_hash="a" * 64,
                )
            assert rejection.value.details["code"] == "DIRECTOR_CONTEXT_REJECTED"
            await DirectorTurnService(session).mark_project_stale(
                project_id=ids["project"], reason="User switched to MANUAL",
            )
            await session.commit()
        async with factory() as session:
            await set_rls_context(session, user_id=ids["user"], workspace_id=ids["workspace"],
                                  project_id=ids["project"])
            rejected_turn = await session.get(DirectorTurn, decision_id)
            assert rejected_turn.status == "completed"
            assert rejected_turn.response_summary["user_decision"]["decision"] == "reject"
            assert (await session.get(DirectorTurn, ids["waiting_turn"])).status == "stale"
            assert (await session.get(NodeRun, ids["node_run"])).status == "completed"
        await engine.dispose()
    finally:
        await _drop_database(dbname)
