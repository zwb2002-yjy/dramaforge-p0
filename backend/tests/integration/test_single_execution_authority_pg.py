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
