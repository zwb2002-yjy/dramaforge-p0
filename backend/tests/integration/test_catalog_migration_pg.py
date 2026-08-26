"""PostgreSQL migration test for stage A+B on an ISOLATED database.

Requires a reachable Postgres. Creates a throwaway database, runs the real
Alembic chain against it (upgrade 0014 -> seed legacy data -> upgrade head ->
downgrade -> re-upgrade), then drops it. Never touches the shared dev database.
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
DB_USER = os.environ.get("TEST_PG_USER", "dramaforge")
DB_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "dramaforge")


def _pg_host() -> str:
    return os.environ.get("TEST_PG_HOST", "127.0.0.1")


def _pg_port() -> str:
    return os.environ.get("TEST_PG_PORT", "5432")


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
        # PG 13+ FORCE terminates lingering sessions (e.g. subprocess alembic).
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.close()


def _seed_legacy_binding(dbname: str) -> dict:
    """Insert a legacy (pre-A+B) agnes image binding with all four flags true."""
    engine = create_engine(_db_sync_url(dbname))
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (email, display_name, password_hash) "
                "VALUES (:e, 'T', 'x') RETURNING id"
            ),
            {"e": f"mig-{uuid.uuid4().hex}@example.com"},
        ).scalar_one()
        workspace_id = conn.execute(
            text("INSERT INTO workspaces (owner_user_id, name) VALUES (:u, :n) RETURNING id"),
            {"u": user_id, "n": f"mig-ws-{uuid.uuid4().hex[:8]}"},
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
                "(id, workspace_id, provider_type, display_name, base_url, protocol_profile, "
                " credential_id, credential_revision, enabled, verification_status, "
                " created_by, updated_by) "
                "VALUES (gen_random_uuid(), :w, 'agnes', 'Agnes', "
                " 'https://api.agnes-ai.cn', 'agnes_cn_v1', "
                " :c, 1, true, 'verified', :u, :u) RETURNING id"
            ),
            {"w": workspace_id, "c": credential_id, "u": user_id},
        ).scalar_one()
        binding_id = conn.execute(
            text(
                "INSERT INTO provider_model_bindings "
                "(id, workspace_id, connection_id, media_type, model_id, purpose, enabled, "
                " documented, contract_tested, account_verified, quality_gated, "
                " created_by, updated_by) "
                "VALUES (gen_random_uuid(), :w, :conn, 'image', 'agnes-image-2.1-flash', "
                " 'keyframe', true, true, true, true, true, :u, :u) RETURNING id"
            ),
            {"w": workspace_id, "conn": connection_id, "u": user_id},
        ).scalar_one()
    engine.dispose()
    return {"workspace_id": workspace_id, "binding_id": binding_id}


@pytest.mark.asyncio
async def test_migration_0015_backfills_and_rolls_back_on_isolated_db() -> None:
    dbname = f"dramaforge_mig_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        _alembic(dbname, "upgrade", "20260803_0014")
        seeded = _seed_legacy_binding(dbname)

        _alembic(dbname, "upgrade", "20260813_0023")
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar()
            assert head == "20260813_0023"
            rows = conn.execute(
                text(
                    "select provider_type, model_id, model_revision "
                    "from provider_model_catalog_entries order by model_id"
                )
            ).fetchall()
            assert len(rows) == 6
            binding = conn.execute(
                text(
                    "select catalog_entry_id, capability_manifest_hash, "
                    "remote_resource_kind, remote_resource_id, invoke_model_value, "
                    "account_verified, quality_gated "
                    "from provider_model_bindings where id = :id"
                ),
                {"id": seeded["binding_id"]},
            ).one()
            # Backfill wrote extension columns; four evidence flags untouched.
            assert binding.catalog_entry_id is not None
            assert binding.capability_manifest_hash is not None
            assert binding.remote_resource_kind == "model"
            assert binding.remote_resource_id == "agnes-image-2.1-flash"
            assert binding.invoke_model_value == "agnes-image-2.1-flash"
            assert binding.account_verified is True
            assert binding.quality_gated is True
            # Catalog is globally readable; non-owner role has no write grant.
            assert (
                conn.execute(
                    text(
                        "select has_table_privilege('dramaforge_app',"
                        " 'provider_model_catalog_entries','INSERT')"
                    )
                ).scalar()
                is False
            )
            runtime_role = conn.execute(
                text(
                    "select rolcanlogin, rolbypassrls, rolsuper, rolpassword "
                    "from pg_authid where rolname='dramaforge_app'"
                )
            ).one()
            assert runtime_role.rolcanlogin is False
            assert runtime_role.rolbypassrls is False
            assert runtime_role.rolsuper is False
            assert runtime_role.rolpassword is None
        engine.dispose()

        # Downgrade drops the new schema; upgrade re-creates it idempotently.
        _alembic(dbname, "downgrade", "20260803_0014")
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "select count(*) from information_schema.tables "
                        "where table_name='provider_model_catalog_entries'"
                    )
                ).scalar()
                == 0
            )
            assert (
                conn.execute(
                    text(
                        "select count(*) from information_schema.columns "
                        "where table_name='provider_operations' "
                        "and column_name='resume_token'"
                    )
                ).scalar()
                == 0
            )
        engine.dispose()

        _alembic(dbname, "upgrade", "20260813_0023")
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            assert (
                conn.execute(text("select count(*) from provider_model_catalog_entries")).scalar()
                == 6
            )
        engine.dispose()
    finally:
        await _drop_db(dbname)


@pytest.mark.asyncio
async def test_identity_review_storage_contract_on_isolated_db() -> None:
    dbname = f"dramaforge_identity_{uuid.uuid4().hex[:10]}"
    try:
        await _create_db(dbname)
        # Upgrade to 0028 (before 0029 which is intentionally irreversible) so
        # the downgrade to 0027 below works.  0029 is verified later via the
        # re-upgrade to head.
        _alembic(dbname, "upgrade", "20260819_0028")

        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            head = conn.execute(text("select version_num from alembic_version")).scalar_one()
            assert head == "20260819_0028"
            agnes_image_revisions = conn.execute(
                text(
                    "select model_revision, lifecycle, capability_manifest_json "
                    "from provider_model_catalog_entries "
                    "where provider_type='agnes' "
                    "and protocol_profile='agnes_cn_v1' "
                    "and model_id='agnes-image-2.1-flash' "
                    "order by model_revision"
                )
            ).fetchall()
            assert [(row.model_revision, row.lifecycle) for row in agnes_image_revisions] == [
                ("v1", "deprecated"),
                ("v2", "active"),
            ]
            image_v2 = agnes_image_revisions[1].capability_manifest_json
            image_output = image_v2["operations"]["image.generate"]["output_constraints"]
            assert image_output["size"] == "1K"
            assert image_output["aspect_ratio"] == "9:16"
            assert (image_output["width"], image_output["height"]) == (736, 1312)
            seedance_2 = conn.execute(
                text(
                    "select model_id, lifecycle from provider_model_catalog_entries "
                    "where provider_type='volcengine' "
                    "and protocol_profile='ark_cn_v1' "
                    "and model_id='doubao-seedance-2-0-260128'"
                )
            ).one()
            assert seedance_2.model_id == "doubao-seedance-2-0-260128"
            assert seedance_2.lifecycle == "active"
            node_types = {
                row[0]
                for row in conn.execute(
                    text(
                        "select enumlabel from pg_enum "
                        "join pg_type on pg_type.oid=pg_enum.enumtypid "
                        "where pg_type.typname='node_type'"
                    )
                )
            }
            assert "identity_review" in node_types
            calibration_length = conn.execute(
                text(
                    "select character_maximum_length from information_schema.columns "
                    "where table_name='characters' and column_name='calibration_state'"
                )
            ).scalar_one()
            assert calibration_length == 32
            removed_columns = conn.execute(
                text(
                    "select count(*) from information_schema.columns "
                    "where (table_name='characters' and column_name='similarity_threshold') "
                    "or (table_name='character_references' "
                    "and column_name in ('face_embedding','embedding_model_version'))"
                )
            ).scalar_one()
            assert removed_columns == 0
        engine.dispose()

        _alembic(dbname, "downgrade", "20260817_0027")
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            assert (
                conn.execute(text("select version_num from alembic_version")).scalar_one()
                == "20260817_0027"
            )
            downgraded = conn.execute(
                text(
                    "select model_revision, lifecycle "
                    "from provider_model_catalog_entries "
                    "where provider_type='agnes' "
                    "and protocol_profile='agnes_cn_v1' "
                    "and model_id='agnes-image-2.1-flash' "
                    "order by model_revision"
                )
            ).fetchall()
            assert [(row.model_revision, row.lifecycle) for row in downgraded] == [
                ("v1", "active"),
                ("v2", "deprecated"),
            ]
        engine.dispose()

        _alembic(dbname, "upgrade", "head")
        engine = create_engine(_db_sync_url(dbname))
        with engine.connect() as conn:
            assert (
                conn.execute(text("select version_num from alembic_version")).scalar_one()
                == "20260826_0040"
            )
            reupgraded = conn.execute(
                text(
                    "select model_revision, lifecycle "
                    "from provider_model_catalog_entries "
                    "where provider_type='agnes' "
                    "and protocol_profile='agnes_cn_v1' "
                    "and model_id='agnes-image-2.1-flash' "
                    "order by model_revision"
                )
            ).fetchall()
            assert [(row.model_revision, row.lifecycle) for row in reupgraded] == [
                ("v1", "deprecated"),
                ("v2", "active"),
            ]
        engine.dispose()
    finally:
        await _drop_db(dbname)
