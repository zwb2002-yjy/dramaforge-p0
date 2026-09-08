"""R2a DirectorTurn migration, constraints, indexes, and RLS on PostgreSQL."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from pg_support import env_target
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[2]
DB_USER = os.environ.get("TEST_PG_USER", "dramaforge")
DB_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "dramaforge")


def _pg_host() -> str:
    return env_target()[0]


def _pg_port() -> str:
    return env_target()[1]


def _admin_url() -> str:
    return os.environ.get(
        "TEST_PG_ADMIN_URL",
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/postgres",
    )


def _sync_url(dbname: str) -> str:
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/{dbname}"


def _async_url(dbname: str) -> str:
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/{dbname}"


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


def _alembic(dbname: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = _async_url(dbname)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_director_turn_migration_constraints_and_rls() -> None:
    dbname = f"dramaforge_director_turn_{uuid.uuid4().hex[:8]}"
    try:
        await _create_database(dbname)
        _alembic(dbname, "upgrade", "head")
        engine = create_engine(_sync_url(dbname))
        ids = {key: uuid.uuid4() for key in ("user", "workspace", "project", "scope")}
        with engine.begin() as connection:
            head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert head == "20260908_0057"
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='director_turns'"
                    )
                )
            }
            assert {
                "workspace_id",
                "project_id",
                "actor_id",
                "request_key",
                "context_hash",
                "model_resolution",
                "transport_record_id",
                "token_usage",
                "provider_cost",
                "output_hash",
                "status",
                "revision",
                "schema_repair_count",
            } <= columns
            policy = connection.execute(
                text(
                    "SELECT policyname FROM pg_policies WHERE tablename='director_turns' "
                    "AND policyname='director_turns_project_scope'"
                )
            ).scalar_one_or_none()
            assert policy == "director_turns_project_scope"
            indexes = {
                row[0]
                for row in connection.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename='director_turns'")
                )
            }
            assert {"ix_director_turns_scope", "ix_director_turns_status"} <= indexes
            recovery_function = connection.execute(
                text(
                    "SELECT to_regprocedure("
                    "'app.recoverable_director_turn_contexts(integer,timestamp with time zone)')"
                )
            ).scalar_one()
            assert recovery_function is not None
            connection.execute(
                text(
                    "INSERT INTO users (id,email,display_name,password_hash) "
                    "VALUES (:id,:email,'Director','x')"
                ),
                {"id": ids["user"], "email": f"turn-{uuid.uuid4().hex}@example.com"},
            )
            connection.execute(
                text(
                    "INSERT INTO workspaces (id,owner_user_id,name) VALUES (:id,:owner,'Turn WS')"
                ),
                {"id": ids["workspace"], "owner": ids["user"]},
            )
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id,workspace_id,name,aspect_ratio,budget_limit) "
                    "VALUES (:id,:workspace,'Turn Project','16:9',0)"
                ),
                {"id": ids["project"], "workspace": ids["workspace"]},
            )
            connection.execute(
                text(
                    "INSERT INTO director_turns "
                    "(workspace_id,project_id,actor_id,scope_type,scope_entity_id,"
                    "request_key,context_hash) "
                    "VALUES (:workspace,:project,:actor,'shot',:scope,'request-unique',:hash)"
                ),
                {
                    "workspace": ids["workspace"],
                    "project": ids["project"],
                    "actor": ids["user"],
                    "scope": ids["scope"],
                    "hash": "a" * 64,
                },
            )
        duplicate = text(
            "INSERT INTO director_turns "
            "(workspace_id,project_id,actor_id,scope_type,scope_entity_id,"
            "request_key,context_hash) "
            "VALUES (:workspace,:project,:actor,'shot',:scope,'request-unique',:hash)"
        )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                duplicate,
                {
                    "workspace": ids["workspace"],
                    "project": ids["project"],
                    "actor": ids["user"],
                    "scope": uuid.uuid4(),
                    "hash": "b" * 64,
                },
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE director_turns SET schema_repair_count=2 "
                    "WHERE project_id=:project AND request_key='request-unique'"
                ),
                {"project": ids["project"]},
            )
        engine.dispose()
        _alembic(dbname, "downgrade", "20260903_0055")
        engine = create_engine(_sync_url(dbname))
        with engine.connect() as connection:
            table_name = connection.execute(
                text("SELECT to_regclass('director_turns')")
            ).scalar_one()
            assert table_name is None
        engine.dispose()
        _alembic(dbname, "upgrade", "head")
    finally:
        await _drop_database(dbname)
