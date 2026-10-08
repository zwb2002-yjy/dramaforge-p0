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
from pg_support import env_target
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]
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
    reason=("set TEST_PG_ENABLED=1 with an explicitly configured isolated PostgreSQL target"),
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
                ' \'{"planning.script": {"model_id": "litellm/script-quality"}}\'::json, :u, :u) '
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
        _alembic(dbname, "upgrade", "20260813_0023")
        seeded = _seed_workspace_default(dbname)

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar()
            assert head == "20260813_0023"
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

        _alembic(dbname, "upgrade", "20260813_0023")
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


@pytest.mark.asyncio
async def test_0086_removes_retired_audio_tts_profile_binding() -> None:
    dbname = f"dramaforge_mp_tts_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        _alembic(dbname, "upgrade", "20261007_0085")
        seeded = _seed_workspace_default(dbname)

        engine = create_engine(_db_sync_url(dbname))
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE production_model_profiles "
                    "SET bindings = CAST(:bindings AS json) WHERE id = :profile_id"
                ),
                {
                    "profile_id": seeded["profile_id"],
                    "bindings": (
                        '{"planning.script":{"model_id":"litellm/script-quality"},'
                        '"audio.tts":{"model_id":"legacy/voice"}}'
                    ),
                },
            )
        engine.dispose()

        _alembic(dbname, "upgrade", "20261008_0086")

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar_one()
            assert head == "20261008_0086"
            bindings = conn.execute(
                text("SELECT bindings FROM production_model_profiles WHERE id = :profile_id"),
                {"profile_id": seeded["profile_id"]},
            ).scalar_one()
            assert "audio.tts" not in bindings
            assert bindings["planning.script"]["model_id"] == "litellm/script-quality"
        engine.dispose()
    finally:
        await _drop_db(dbname)

@pytest.mark.asyncio
async def test_0087_removes_binding_pricing_and_fallback_columns() -> None:
    dbname = f"dramaforge_provider_cut_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        _alembic(dbname, "upgrade", "20261008_0086")

        engine = create_engine(_db_sync_url(dbname))
        with engine.begin() as conn:
            user_id = conn.execute(
                text(
                    "INSERT INTO users (email, display_name, password_hash) "
                    "VALUES (:e, 'Provider cutover', 'x') RETURNING id"
                ),
                {"e": f"provider-cut-{uuid.uuid4().hex}@example.com"},
            ).scalar_one()
            workspace_id = conn.execute(
                text(
                    "INSERT INTO workspaces (owner_user_id, name) "
                    "VALUES (:u, :n) RETURNING id"
                ),
                {"u": user_id, "n": f"provider-cut-{uuid.uuid4().hex[:8]}"},
            ).scalar_one()
            project_id = conn.execute(
                text(
                    "INSERT INTO projects (workspace_id, name, aspect_ratio, budget_limit) "
                    "VALUES (:w, 'Provider cutover', '9:16', 0) RETURNING id"
                ),
                {"w": workspace_id},
            ).scalar_one()
            credential_id = conn.execute(
                text(
                    "INSERT INTO encrypted_provider_credentials "
                    "(workspace_id, provider, ciphertext, key_version) "
                    "VALUES (:w, 'agnes', 'x', 'v1') RETURNING id"
                ),
                {"w": workspace_id},
            ).scalar_one()
            connection_id = conn.execute(
                text(
                    "INSERT INTO provider_connections "
                    "(workspace_id, provider_type, display_name, base_url, protocol_profile, "
                    "credential_id, credential_revision, enabled, verification_status, "
                    "created_by, updated_by) "
                    "VALUES (:w, 'agnes', 'Agnes', 'https://api.agnes-ai.cn', "
                    "'agnes_cn_v1', :credential, 1, true, 'verified', :u, :u) "
                    "RETURNING id"
                ),
                {"w": workspace_id, "credential": credential_id, "u": user_id},
            ).scalar_one()
            binding_id = conn.execute(
                text(
                    "INSERT INTO provider_model_bindings "
                    "(workspace_id, connection_id, media_type, model_id, purpose, enabled, "
                    "documented, contract_tested, account_verified, quality_gated, "
                    "pricing_snapshot_json, created_by, updated_by) "
                    "VALUES (:w, :connection, 'image', 'agnes-image-2.1-flash', "
                    "'keyframe', true, true, true, true, false, "
                    "CAST(:pricing AS json), :u, :u) RETURNING id"
                ),
                {
                    "w": workspace_id,
                    "connection": connection_id,
                    "pricing": '{"unit_amount":"0.1","currency":"USD"}',
                    "u": user_id,
                },
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO project_provider_bindings "
                    "(project_id, workspace_id, purpose, model_binding_id, "
                    "selection_strategy, fallback_policy, updated_by) "
                    "VALUES (:project, :workspace, 'keyframe', :binding, "
                    "'explicit_binding', 'none', :u)"
                ),
                {
                    "project": project_id,
                    "workspace": workspace_id,
                    "binding": binding_id,
                    "u": user_id,
                },
            )
        engine.dispose()

        _alembic(dbname, "upgrade", "20261008_0087")

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar_one()
            assert head == "20261008_0087"
            retired = conn.execute(
                text(
                    "SELECT table_name, column_name "
                    "FROM information_schema.columns "
                    "WHERE (table_name='provider_model_bindings' "
                    "AND column_name='pricing_snapshot_json') "
                    "OR (table_name='project_provider_bindings' "
                    "AND column_name='fallback_policy')"
                )
            ).fetchall()
            assert retired == []
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name='provider_model_catalog_entries' "
                        "AND column_name='pricing_snapshot_json'"
                    )
                ).scalar_one()
                == 1
            )
        engine.dispose()
    finally:
        await _drop_db(dbname)

