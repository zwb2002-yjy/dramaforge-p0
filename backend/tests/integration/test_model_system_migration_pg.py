"""Migration A preserves live Binding IDs and fails closed on account evidence."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from pg_support import alembic_head, alembic_parent, env_target
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "20260929_0074"
DB_USER = os.environ.get("TEST_PG_USER", "dramaforge")
DB_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "dramaforge")


def _sync_url(dbname: str) -> str:
    host, port = env_target()
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{host}:{port}/{dbname}"


def _async_url(dbname: str) -> str:
    host, port = env_target()
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{host}:{port}/{dbname}"


def _available() -> bool:
    try:
        engine = create_engine(_sync_url("dramaforge"), connect_args={"connect_timeout": 2})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _available(),
    reason="requires an explicitly configured isolated PostgreSQL test service",
)


async def _admin() -> asyncpg.Connection:
    host, port = env_target()
    return await asyncpg.connect(
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{host}:{port}/postgres"
    )


def _migrate(dbname: str, command: str, target: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = _async_url(dbname)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _seed_bound_model(dbname: str) -> dict[str, str]:
    ids = {
        name: str(uuid4())
        for name in (
            "user",
            "workspace",
            "project",
            "credential",
            "connection",
            "revision",
            "binding",
            "project_binding",
        )
    }
    engine = create_engine(_sync_url(dbname))
    with engine.begin() as connection:
        catalog = connection.execute(
            text(
                "SELECT id, contract_manifest_hash FROM provider_model_catalog_entries "
                "WHERE provider_type = 'minimax' AND model_id = 'MiniMax-H3' "
                "AND model_revision = 'v1'"
            )
        ).one()
        ids["catalog"] = str(catalog.id)
        connection.execute(
            text(
                "INSERT INTO users (id,email,display_name,password_hash) "
                "VALUES (:id,:email,'Cutover Owner','hash')"
            ),
            {"id": ids["user"], "email": f"cutover-{uuid4().hex}@example.invalid"},
        )
        connection.execute(
            text("INSERT INTO workspaces (id,owner_user_id,name) VALUES (:id,:owner,'Cutover')"),
            {"id": ids["workspace"], "owner": ids["user"]},
        )
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id,workspace_id,name,stage,aspect_ratio,target_platform,style_bible,"
                "budget_limit,budget_currency,provider_dispatch_frozen) "
                "VALUES (:id,:workspace,'Cutover Project','draft','9:16','general',"
                "'{}'::json,0,'USD',false)"
            ),
            {"id": ids["project"], "workspace": ids["workspace"]},
        )
        connection.execute(
            text(
                "INSERT INTO encrypted_provider_credentials "
                "(id,workspace_id,provider,revision_no,ciphertext,key_version) "
                "VALUES (:id,:workspace,'minimax',1,'synthetic','test')"
            ),
            {"id": ids["credential"], "workspace": ids["workspace"]},
        )
        connection.execute(
            text(
                "INSERT INTO provider_connections "
                "(id,workspace_id,provider_type,display_name,base_url,protocol_profile,"
                "credential_id,credential_revision,enabled,verification_status,"
                "created_by,updated_by) "
                "VALUES (:id,:workspace,'minimax','MiniMax','https://example.invalid',"
                "'minimax_cn_v1',:credential,1,true,'verified',:owner,:owner)"
            ),
            {
                "id": ids["connection"], "workspace": ids["workspace"],
                "credential": ids["credential"], "owner": ids["user"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO provider_connection_revisions "
                "(id,connection_id,revision_no,provider_type,protocol_profile,base_url,"
                "credential_revision_id) VALUES (:id,:connection,1,'minimax',"
                "'minimax_cn_v1','https://example.invalid',:credential)"
            ),
            {
                "id": ids["revision"], "connection": ids["connection"],
                "credential": ids["credential"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO provider_model_bindings "
                "(id,workspace_id,connection_id,media_type,model_id,purpose,enabled,documented,"
                "contract_tested,account_verified,quality_gated,catalog_entry_id,"
                "capability_manifest_hash,remote_resource_kind,remote_resource_id,invoke_model_value,"
                "pricing_snapshot_json,created_by,updated_by) "
                "VALUES (:id,:workspace,:connection,'video','MiniMax-H3','video',true,true,"
                "true,true,false,:catalog,:hash,'model','MiniMax-H3','MiniMax-H3',"
                "'{}'::json,:owner,:owner)"
            ),
            {
                "id": ids["binding"], "workspace": ids["workspace"],
                "connection": ids["connection"], "catalog": ids["catalog"],
                "hash": catalog.contract_manifest_hash, "owner": ids["user"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO project_provider_bindings "
                "(id,project_id,workspace_id,purpose,model_binding_id,selection_strategy,"
                "fallback_policy,updated_by) "
                "VALUES (:id,:project,:workspace,'video',:binding,'explicit_binding','none',:owner)"
            ),
            {
                "id": ids["project_binding"], "project": ids["project"],
                "workspace": ids["workspace"], "binding": ids["binding"], "owner": ids["user"],
            },
        )
    engine.dispose()
    return ids


@pytest.mark.asyncio
async def test_migration_a_preserves_binding_and_requires_new_positive_evidence() -> None:
    dbname = f"dramaforge_model_cutover_{uuid4().hex[:10]}"
    admin = await _admin()
    try:
        await admin.execute(f'CREATE DATABASE "{dbname}"')
        _migrate(dbname, "upgrade", alembic_parent(REVISION))
        ids = _seed_bound_model(dbname)
        _migrate(dbname, "upgrade", REVISION)
        engine = create_engine(_sync_url(dbname))
        with engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version"))
            assert current.scalar_one() == REVISION
            row = connection.execute(
                text(
                    "SELECT id,binding_target_kind,model_capability_revision_id,canonical_model_id "
                    "FROM provider_model_bindings WHERE id = :id"
                ),
                {"id": ids["binding"]},
            ).one()
            assert str(row.id) == ids["binding"]
            assert row.binding_target_kind == "global_model"
            assert str(row.model_capability_revision_id) == ids["catalog"]
            assert row.canonical_model_id == "MiniMax-H3"
            assert str(connection.execute(
                text("SELECT model_binding_id FROM project_provider_bindings WHERE id = :id"),
                {"id": ids["project_binding"]},
            ).scalar_one()) == ids["binding"]
            availability_count = connection.execute(
                text("SELECT count(*) FROM provider_model_availability")
            ).scalar_one()
            evidence_count = connection.execute(
                text("SELECT count(*) FROM provider_availability_evidence")
            ).scalar_one()
            assert availability_count == 0
            assert evidence_count == 0
            manifest = connection.execute(
                text(
                    "SELECT manifest_json,manifest_hash,implementation_status "
                    "FROM model_capability_revisions WHERE id = :id"
                ),
                {"id": ids["catalog"]},
            ).one()
            assert "lifecycle" not in manifest.manifest_json
            assert manifest.implementation_status == "manifest_mapped"
            assert connection.execute(
                text(
                    "SELECT lifecycle FROM model_publication_states "
                    "WHERE model_capability_revision_id = :id"
                ),
                {"id": ids["catalog"]},
            ).scalar_one() == "unknown"
            for table in (
                "connection_discovered_models",
                "connection_model_capability_revisions",
                "provider_availability_evidence",
            ):
                assert not connection.execute(
                    text("SELECT has_table_privilege('dramaforge_app', :table, 'UPDATE')"),
                    {"table": table},
                ).scalar_one()
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE provider_model_bindings "
                    "SET binding_target_kind = NULL, model_capability_revision_id = NULL "
                    "WHERE id = :id"
                ),
                {"id": ids["binding"]},
            )
        engine.dispose()
        _migrate(dbname, "downgrade", alembic_parent(REVISION))
        _migrate(dbname, "upgrade", alembic_head())
        engine = create_engine(_sync_url(dbname))
        with engine.connect() as connection:
            assert str(connection.execute(
                text("SELECT model_binding_id FROM project_provider_bindings WHERE id = :id"),
                {"id": ids["project_binding"]},
            ).scalar_one()) == ids["binding"]
        engine.dispose()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
        await admin.close()
