"""PostgreSQL migration proof for the staged repair tables."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from pg_support import alembic_head, alembic_parent, env_target
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[2]
# The migration this test proves; its own file owns the revision id.
REVISION = "20260915_0069"
DB_USER = os.environ.get("TEST_PG_USER", "dramaforge")
DB_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "dramaforge")


def _pg_host() -> str:
    return env_target()[0]


def _pg_port() -> str:
    return env_target()[1]


def _pg_admin_url() -> str:
    default = f"postgresql://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/postgres"
    return os.environ.get("TEST_PG_ADMIN_URL", default)


def _db_sync_url(dbname: str) -> str:
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/{dbname}"


def _db_async_url(dbname: str) -> str:
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{_pg_host()}:{_pg_port()}/{dbname}"


def _pg_available_sync() -> bool:
    try:
        engine = create_engine(
            _db_sync_url("dramaforge"),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _alembic(dbname: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = _db_async_url(dbname)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    )


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _pg_available_sync(),
    reason=(
        "set TEST_PG_ENABLED=1 with an explicitly configured isolated PostgreSQL target"
    ),
)


async def _create_db(name: str) -> None:
    admin = await asyncpg.connect(_pg_admin_url())
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


async def _drop_db(name: str) -> None:
    admin = await asyncpg.connect(_pg_admin_url())
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.close()


def _seed_scope(dbname: str) -> dict[str, str]:
    engine = create_engine(_db_sync_url(dbname))
    ids = {
        "user_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "episode_id": str(uuid.uuid4()),
        "scene_id": str(uuid.uuid4()),
        "shot_id": str(uuid.uuid4()),
        "artifact_id": str(uuid.uuid4()),
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, password_hash) "
                "VALUES (:u, :e, 'Repair Owner', 'x')"
            ),
            {"u": ids["user_id"], "e": f"repair-{uuid.uuid4().hex[:8]}@example.com"},
        )
        conn.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name) "
                "VALUES (:w, :u, 'Repair Workspace')"
            ),
            {"w": ids["workspace_id"], "u": ids["user_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, workspace_id, name, stage, aspect_ratio, target_platform, "
                " style_bible, budget_limit, budget_currency, provider_dispatch_frozen) "
                "VALUES (:p, :w, 'Repair Project', 'draft', '16:9', 'general', "
                "        '{}'::json, 0, 'USD', false)"
            ),
            {"p": ids["project_id"], "w": ids["workspace_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO episodes (id, project_id, episode_number, title, synopsis) "
                "VALUES (:e, :p, 1, 'E1', '')"
            ),
            {"e": ids["episode_id"], "p": ids["project_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO scenes "
                "(id, episode_id, scene_number, location_name, time_of_day, synopsis) "
                "VALUES (:s, :e, 1, 'Room', 'day', '')"
            ),
            {"s": ids["scene_id"], "e": ids["episode_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO shots "
                "(id, project_id, scene_id, shot_number, shot_type, camera_move, "
                " visual_description, dialogue, status, sort_order) "
                "VALUES (:sh, :p, :s, 1, 'medium', 'static', 'A waits', '', 'draft', 1)"
            ),
            {"sh": ids["shot_id"], "p": ids["project_id"], "s": ids["scene_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO artifacts "
                "(id, project_id, artifact_type, storage_state, object_key, "
                " content_hash, mime_type, byte_size) "
                "VALUES (:a, :p, 'image', 'available', :k, :h, 'image/png', 8)"
            ),
            {
                "a": ids["artifact_id"],
                "p": ids["project_id"],
                "k": f"obj/{uuid.uuid4().hex}.png",
                "h": uuid.uuid4().hex * 2,
            },
        )
    engine.dispose()
    return ids


_INSERT_REQUEST = text(
    "INSERT INTO repair_requests "
    "(id, project_id, shot_id, created_by, option, plan_schema_version, plan_hash, "
    " annotation_ids, annotation_summary, source_formal_artifact_id, input_fingerprint, "
    " request_key, request_hash) "
    "VALUES (gen_random_uuid(), :p, :sh, :u, :option, 1, :hash, '[]'::jsonb, '{}'::jsonb, "
    "        :a, :hash, :key, :hash) RETURNING id"
)


@pytest.mark.asyncio
async def test_repair_migration_constraints_rls_and_round_trip() -> None:
    dbname = f"dramaforge_repair_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        _alembic(dbname, "upgrade", "head")
        seeded = _seed_scope(dbname)
        digest = hashlib.sha256(b"repair-plan").hexdigest()

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar()
            assert head == alembic_head()
            for table in ("repair_requests", "repair_steps"):
                columns = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "select column_name from information_schema.columns "
                            "where table_name=:t"
                        ),
                        {"t": table},
                    ).all()
                }
                assert columns, f"{table} was not created"
                assert (
                    conn.execute(
                        text("select policyname from pg_policies where tablename=:t"),
                        {"t": table},
                    ).scalar_one()
                    == f"{table}_scope"
                )
                forced = conn.execute(
                    text("select relforcerowsecurity from pg_class where relname=:t"),
                    {"t": table},
                ).scalar_one()
                assert forced is True

            payload = {
                "p": seeded["project_id"],
                "sh": seeded["shot_id"],
                "u": seeded["user_id"],
                "a": seeded["artifact_id"],
                "hash": digest,
                "key": "repair:pg",
                "option": "regenerate_keyframe_then_video",
            }
            request_id = conn.execute(_INSERT_REQUEST, payload).scalar_one()
            conn.commit()

            # The request key is unique per project.
            with pytest.raises(IntegrityError):
                conn.execute(_INSERT_REQUEST, {**payload, "option": "rerun_video"})
            conn.rollback()

            # The option vocabulary is enforced by the database.
            with pytest.raises(IntegrityError):
                conn.execute(_INSERT_REQUEST, {**payload, "key": "repair:pg2", "option": "magic"})
            conn.rollback()

            # One step per ordinal, and steps cascade with their request.
            step_sql = text(
                "INSERT INTO repair_steps "
                "(id, repair_request_id, project_id, ordinal, stage) "
                "VALUES (gen_random_uuid(), :r, :p, 1, 'keyframe_regenerate')"
            )
            conn.execute(step_sql, {"r": request_id, "p": seeded["project_id"]})
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(step_sql, {"r": request_id, "p": seeded["project_id"]})
            conn.rollback()
        engine.dispose()

        _alembic(dbname, "downgrade", alembic_parent(REVISION))
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            remaining = conn.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_name in ('repair_requests','repair_steps')"
                )
            ).scalar_one()
            assert remaining == 0
        engine.dispose()
        _alembic(dbname, "upgrade", "head")
    finally:
        await _drop_db(dbname)
