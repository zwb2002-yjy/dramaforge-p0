"""PostgreSQL migration + RLS test for production_model_profiles.

Runs the real Alembic chain on an ISOLATED throwaway database: upgrade to head →
schema/RLS/index smoke → data insert → partial-unique-default check → downgrade
→ re-upgrade → drop. Never touches the shared dev database.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_ADMIN = "postgresql://dramaforge:dramaforge@127.0.0.1:5432/postgres"
DB_USER = "dramaforge"
DB_PASSWORD = "dramaforge"
DB_HOST = "127.0.0.1:5432"


def _pg_admin_url() -> str:
    return os.environ.get("TEST_PG_ADMIN_URL", DEFAULT_ADMIN)


def _db_sync_url(dbname: str) -> str:
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{dbname}"


def _db_async_url(dbname: str) -> str:
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{dbname}"


def _pg_available_sync() -> bool:
    try:
        engine = create_engine(_db_sync_url("dramaforge"), pool_pre_ping=True)
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
    not _pg_available_sync(),
    reason="PostgreSQL not reachable; start docker compose postgres",
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


def _seed_workspace_default(dbname: str) -> dict:
    """Insert a user/workspace and a workspace-default profile row."""
    engine = create_engine(_db_sync_url(dbname))
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (email, display_name, password_hash) "
                "VALUES (:e, 'T', 'x') RETURNING id"
            ),
            {"e": f"mp-{uuid.uuid4().hex}@example.com"},
        ).scalar_one()
        workspace_id = conn.execute(
            text("INSERT INTO workspaces (owner_user_id, name) VALUES (:u, :n) RETURNING id"),
            {"u": user_id, "n": f"mp-ws-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        profile_id = conn.execute(
            text(
                "INSERT INTO production_model_profiles "
                "(id, workspace_id, name, version, is_default, bindings, created_by, updated_by) "
                "VALUES (gen_random_uuid(), :w, '默认方案', 1, true, "
                ' \'{"planning.script": {"model_id": "litellm/text-llm"}}\'::json, :u, :u) '
                "RETURNING id"
            ),
            {"w": workspace_id, "u": user_id},
        ).scalar_one()
    engine.dispose()
    return {
        "workspace_id": workspace_id,
        "profile_id": profile_id,
        "user_id": user_id,
    }


@pytest.mark.asyncio
async def test_model_profiles_migration_and_rls_on_isolated_db() -> None:
    dbname = f"dramaforge_mp_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        _alembic(dbname, "upgrade", "head")
        seeded = _seed_workspace_default(dbname)

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar()
            assert head == "20260811_0017"
            # Table + RLS policy exist.
            assert (
                conn.execute(
                    text(
                        "select count(*) from information_schema.tables "
                        "where table_name='production_model_profiles'"
                    )
                ).scalar()
                == 1
            )
            policy = conn.execute(
                text(
                    "select policyname from pg_policies "
                    "where tablename='production_model_profiles' "
                    "and policyname='production_model_profiles_workspace_scope'"
                )
            ).scalar_one_or_none()
            assert policy is not None
            # Partial unique index: only one workspace default per workspace.
            second_default_sql = text(
                "INSERT INTO production_model_profiles "
                "(id, workspace_id, name, version, is_default, bindings, created_by, updated_by) "
                "VALUES (gen_random_uuid(), :w, '第二个默认', 1, true, '{}'::json, :u, :u) "
                "RETURNING id"
            )
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                conn.execute(
                    second_default_sql,
                    {"w": seeded["workspace_id"], "u": seeded["user_id"]},
                )
            # The failed insert aborted the transaction; recover before continuing.
            conn.rollback()
            # A non-default profile in the same workspace is allowed.
            non_default = conn.execute(
                text(
                    "INSERT INTO production_model_profiles "
                    "(id, workspace_id, name, version, is_default, bindings, "
                    "created_by, updated_by) "
                    "VALUES (gen_random_uuid(), :w, '非默认', 1, false, '{}'::json, :u, :u) "
                    "RETURNING id"
                ),
                {"w": seeded["workspace_id"], "u": seeded["user_id"]},
            ).scalar_one()
            assert non_default is not None
            # A project profile (project_id set) may exist alongside the default.
            project_id = conn.execute(
                text(
                    "INSERT INTO projects (workspace_id, name, aspect_ratio, budget_limit) "
                    "VALUES (:w, 'P', '9:16', 0) RETURNING id"
                ),
                {"w": seeded["workspace_id"]},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO production_model_profiles "
                    "(id, workspace_id, project_id, name, version, is_default, "
                    "bindings, created_by, updated_by) "
                    "VALUES (gen_random_uuid(), :w, :p, '项目方案', 1, false, '{}'::json, :u, :u)"
                ),
                {"w": seeded["workspace_id"], "p": project_id, "u": seeded["user_id"]},
            )
            # RLS policy uses the workspace owner's context (policy exists).
            assert (
                conn.execute(
                    text(
                        "select count(*) from pg_policies "
                        "where tablename='production_model_profiles' "
                        "and policyname='production_model_profiles_workspace_scope'"
                    )
                ).scalar()
                == 1
            )
        engine.dispose()

        # Downgrade drops the table; re-upgrade recreates it.
        _alembic(dbname, "downgrade", "20260810_0016")
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "select count(*) from information_schema.tables "
                        "where table_name='production_model_profiles'"
                    )
                ).scalar()
                == 0
            )
        engine.dispose()

        _alembic(dbname, "upgrade", "head")
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "select count(*) from information_schema.tables "
                        "where table_name='production_model_profiles'"
                    )
                ).scalar()
                == 1
            )
        engine.dispose()
    finally:
        await _drop_db(dbname)
