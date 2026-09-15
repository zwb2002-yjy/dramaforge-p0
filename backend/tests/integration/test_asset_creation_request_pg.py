"""PostgreSQL migration proof for the asset creation-request identity.

Runs the real Alembic chain on an ISOLATED throwaway database and checks the
partial unique index that makes a retried "artifact becomes an asset"
submission return the original card instead of creating a second one.
"""

from __future__ import annotations

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
REVISION = "20260915_0067"
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


def _seed_project(dbname: str) -> dict[str, str]:
    """Insert workspace + project + one stored image artifact."""
    engine = create_engine(_db_sync_url(dbname))
    ids = {
        "user_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, password_hash) "
                "VALUES (:u, :e, 'Asset Owner', 'x')"
            ),
            {"u": ids["user_id"], "e": f"asset-{uuid.uuid4().hex[:8]}@example.com"},
        )
        conn.execute(
            text(
                "INSERT INTO workspaces (id, owner_user_id, name) "
                "VALUES (:w, :u, 'Asset Workspace')"
            ),
            {"w": ids["workspace_id"], "u": ids["user_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, workspace_id, name, stage, aspect_ratio, target_platform, "
                " style_bible, budget_limit, budget_currency, provider_dispatch_frozen) "
                "VALUES (:p, :w, 'Asset Project', 'draft', '16:9', 'general', "
                "        '{}'::json, 0, 'USD', false)"
            ),
            {"p": ids["project_id"], "w": ids["workspace_id"]},
        )
        ids["artifact_id"] = str(
            conn.execute(
                text(
                    "INSERT INTO artifacts "
                    "(id, project_id, artifact_type, storage_state, object_key, "
                    " content_hash, mime_type, byte_size) "
                    "VALUES (gen_random_uuid(), :p, 'image', 'available', :k, :h, 'image/png', 8) "
                    "RETURNING id"
                ),
                {"p": ids["project_id"], "k": f"obj/{uuid.uuid4().hex}.png", "h": "a" * 64},
            ).scalar_one()
        )
    engine.dispose()
    return ids


_INSERT_ASSET = text(
    "INSERT INTO assets "
    "(id, project_id, kind, name, description, status, metadata, version, "
    " creation_request_key, creation_request_hash) "
    "VALUES (gen_random_uuid(), :p, 'character', :n, '', 'active', '{}'::json, 1, :k, :h) "
    "RETURNING id"
)


@pytest.mark.asyncio
async def test_asset_creation_request_index_and_migration_round_trip() -> None:
    dbname = f"dramaforge_asset_req_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        _alembic(dbname, "upgrade", "head")
        seeded = _seed_project(dbname)

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar()
            assert head == alembic_head()
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name='assets'"
                    )
                ).all()
            }
            assert {"creation_request_key", "creation_request_hash"} <= columns

            first = conn.execute(
                _INSERT_ASSET,
                {"p": seeded["project_id"], "n": "林墨", "k": "add:asset:pg", "h": "b" * 64},
            ).scalar_one()
            conn.commit()

            # Same key in the same project is rejected by the database itself.
            with pytest.raises(IntegrityError):
                conn.execute(
                    _INSERT_ASSET,
                    {
                        "p": seeded["project_id"],
                        "n": "林墨二号",
                        "k": "add:asset:pg",
                        "h": "c" * 64,
                    },
                )
            conn.rollback()

            # A different key for the same artifact/name pair is a normal new row;
            # one artifact may legitimately back more than one explicit asset.
            second = conn.execute(
                _INSERT_ASSET,
                {"p": seeded["project_id"], "n": "林墨三号", "k": "add:asset:pg2", "h": "d" * 64},
            ).scalar_one()
            conn.commit()
            assert second != first

            # Rows without a key are not constrained: pre-existing cards stay valid.
            for name in ("旧资产甲", "旧资产乙"):
                conn.execute(
                    _INSERT_ASSET,
                    {"p": seeded["project_id"], "n": name, "k": None, "h": None},
                )
            conn.commit()

            # The key is scoped per project, so another project may reuse it.
            other = _seed_project(dbname)
            conn.execute(
                _INSERT_ASSET,
                {"p": other["project_id"], "n": "林墨", "k": "add:asset:pg", "h": "e" * 64},
            )
            conn.commit()
        engine.dispose()

        # Downgrade removes the columns and the index; re-upgrade must be clean.
        # Target this revision's own parent: counting steps back from the head
        # silently retargets itself whenever a later migration is added.
        _alembic(dbname, "downgrade", alembic_parent(REVISION))
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name='assets'"
                    )
                ).all()
            }
            assert "creation_request_key" not in columns
        engine.dispose()
        _alembic(dbname, "upgrade", "head")
    finally:
        await _drop_db(dbname)
