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
            for key in ("user", "workspace", "project", "scope", "turn", "stale_turn")
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

        from app.director.turn_models import DirectorTurn
        from app.workers import jobs

        monkeypatch.setattr(jobs, "get_session_factory", lambda: factory)
        recovery = await jobs.recover_interrupted_director_turns({"job_id": "restart-proof"})
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
        await engine.dispose()
    finally:
        await _drop_database(dbname)
