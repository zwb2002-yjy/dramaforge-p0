"""The unreleased cleanup leaves one executable model/Director authority."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from app.providers.catalog_loader import CATALOG_MODELS, hash_manifest
from pg_support import alembic_head
from test_director_turn_lifecycle_pg import (
    _admin_url,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

BACKEND = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_current_schema_has_one_model_authority_and_rejects_downgrade() -> None:
    dbname = f"single_authority_{uuid4().hex[:8]}"
    await _create_database(dbname)
    try:
        environment = {**os.environ, "DATABASE_URL": _async_url(dbname)}
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr
        connection = await asyncpg.connect(_admin_url().rsplit("/", 1)[0] + f"/{dbname}")
        try:
            assert (
                await connection.fetchval("SELECT version_num FROM alembic_version")
                == alembic_head()
            )
            # Deleted projects retain their identity while freeing the active name.
            owner_id, workspace_id, old_id, new_id = (uuid4() for _ in range(4))
            await connection.execute(
                "INSERT INTO users(id,email,display_name,password_hash,is_active,version) "
                "VALUES($1,$2,'Deletion test','not-a-login',true,1)",
                owner_id,
                f"deletion-{owner_id}@example.test",
            )
            await connection.execute(
                "INSERT INTO workspaces(id,owner_user_id,name,version) VALUES($1,$2,'Test',1)",
                workspace_id,
                owner_id,
            )
            insert_project = (
                "INSERT INTO projects(id,workspace_id,name,stage,aspect_ratio,target_platform,"
                "style_bible,budget_limit,budget_currency,provider_dispatch_frozen,version) "
                "VALUES($1,$2,'Same name','draft','9:16','general','{}',0,'USD',false,1)"
            )
            await connection.execute(insert_project, old_id, workspace_id)
            with pytest.raises(asyncpg.UniqueViolationError):
                await connection.execute(insert_project, new_id, workspace_id)
            await connection.execute("UPDATE projects SET deleted_at=now() WHERE id=$1", old_id)
            await connection.execute(insert_project, new_id, workspace_id)
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM projects WHERE workspace_id=$1",
                    workspace_id,
                )
                == 2
            )
            assert (
                await connection.fetchval(
                    "SELECT id FROM projects WHERE workspace_id=$1 AND deleted_at IS NULL",
                    workspace_id,
                )
                == new_id
            )
            for table in (
                "model_capability_revisions",
                "connection_model_capability_revisions",
                "protocol_contract_revisions",
                "runtime_handler_revisions",
                "product_policy_revisions",
                "product_policy_states",
                "product_policy_events",
            ):
                assert await connection.fetchval("SELECT to_regclass($1)", table) is None
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name='provider_model_bindings' "
                    "AND column_name IN ('binding_target_kind','model_capability_revision_id',"
                    "'connection_model_capability_revision_id')"
                )
                == 0
            )
            assert not await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_constraint "
                "WHERE conname='uq_provider_connection_profile')"
            )
            for table in ("node_runs", "provider_operations", "artifacts", "director_turns"):
                assert await connection.fetchval("SELECT to_regclass($1)", table) is not None
            assert await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_trigger "
                "WHERE tgname='provider_availability_evidence_immutable')"
            )
            for manifest in CATALOG_MODELS:
                stored = await connection.fetchrow(
                    "SELECT capability_manifest_json,contract_manifest_hash,lifecycle "
                    "FROM provider_model_catalog_entries WHERE provider_type=$1 "
                    "AND protocol_profile=$2 AND model_id=$3 AND model_revision=$4",
                    manifest["provider_type"],
                    manifest["protocol_profile"],
                    manifest["model_id"],
                    manifest["model_revision"],
                )
                assert stored is not None
                assert json.loads(stored["capability_manifest_json"]) == manifest
                assert stored["contract_manifest_hash"] == hash_manifest(manifest)
                assert stored["lifecycle"] == "active"
        finally:
            await connection.close()
        downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "20261007_0083"],
            cwd=BACKEND,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert downgrade.returncode != 0
        assert "irreversible" in downgrade.stderr
    finally:
        await _drop_database(dbname)
