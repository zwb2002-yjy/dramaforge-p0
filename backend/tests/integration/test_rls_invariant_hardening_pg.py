"""PostgreSQL proof for the 20261030_0095 RLS/invariant hardening.

Creates a throwaway database, runs the real Alembic chain, asserts the schema
invariants the audit required, then downgrades one step and re-upgrades.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Asset, AssetTag, AssetTagLink
from app.providers.availability_models import (
    ProviderAvailabilityEvidence,
    ProviderModelAvailability,
)
from app.providers.models import ProviderConnection, ProviderConnectionRevision
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

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


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _pg_available_sync(),
    reason=("set TEST_PG_ENABLED=1 with an explicitly configured isolated PostgreSQL target"),
)


def _assert_schema_invariants(engine) -> None:
    with engine.connect() as conn:
        for constraint in ("fk_shot_human_locks_shot", "fk_exports_episode"):
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM pg_constraint "
                        "WHERE conname = :name AND contype = 'f'"
                    ),
                    {"name": constraint},
                ).scalar()
                == 1
            ), constraint

        for table in (
            "provider_availability_evidence",
            "provider_model_availability",
        ):
            qual = conn.execute(
                text("SELECT qual FROM pg_policies WHERE policyname = :name"),
                {"name": f"{table}_workspace_scope"},
            ).scalar_one()
            assert "owner_user_id" in qual, (table, qual)

        link_qual = conn.execute(
            text(
                "SELECT qual FROM pg_policies "
                "WHERE policyname = 'asset_tag_links_project_scope'"
            )
        ).scalar_one()
        assert "asset_tags" in link_qual and "assets" in link_qual, link_qual

        assert (
            conn.execute(
                text(
                    "SELECT to_regprocedure("
                    "'app.resumable_provider_node_run_contexts(integer,text)')"
                )
            ).scalar()
            is None
        )
        assert (
            conn.execute(
                text(
                    "SELECT to_regprocedure("
                    "'app.resumable_provider_node_run_contexts("
                    "integer,text,uuid,timestamptz)')"
                )
            ).scalar()
            is not None
        )

        for table in ("key_rotation_audits", "instance_bootstrap_state"):
            assert not conn.execute(
                text("SELECT has_table_privilege('dramaforge_app', :t, 'UPDATE')"),
                {"t": table},
            ).scalar()
            assert not conn.execute(
                text("SELECT has_table_privilege('dramaforge_app', :t, 'DELETE')"),
                {"t": table},
            ).scalar()
            assert conn.execute(
                text("SELECT has_table_privilege('dramaforge_app', :t, 'SELECT')"),
                {"t": table},
            ).scalar()

        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE indexname = 'uq_model_profile_workspace_name_null_project'"
                )
            ).scalar()
            == 1
        )


def _assert_null_project_profile_name_is_unique(dbname: str) -> None:
    engine = create_engine(_db_sync_url(dbname))
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (email, display_name, password_hash) "
                "VALUES (:e, 'T', 'x') RETURNING id"
            ),
            {"e": f"hardening-{uuid.uuid4().hex}@example.com"},
        ).scalar_one()
        workspace_id = conn.execute(
            text("INSERT INTO workspaces (owner_user_id, name) VALUES (:u, :n) RETURNING id"),
            {"u": user_id, "n": f"hardening-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO production_model_profiles "
                "(id, workspace_id, name, created_by, updated_by) "
                "VALUES (gen_random_uuid(), :w, 'default', :u, :u)"
            ),
            {"w": workspace_id, "u": user_id},
        )
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO production_model_profiles "
                    "(id, workspace_id, name, created_by, updated_by) "
                    "VALUES (gen_random_uuid(), :w, 'default', :u, :u)"
                ),
                {"w": workspace_id, "u": user_id},
            )
    except IntegrityError:
        pass
    else:
        raise AssertionError("duplicate workspace-level profile name was accepted")
    finally:
        engine.dispose()


def _assert_rls_enforces_both_ownership_boundaries(engine) -> None:
    with Session(engine, expire_on_commit=False) as session:
        owner = User(email=f"owner-{uuid.uuid4().hex}@example.com",
                     display_name="Owner", password_hash="x")
        outsider = User(email=f"outsider-{uuid.uuid4().hex}@example.com",
                        display_name="Outsider", password_hash="x")
        session.add_all([owner, outsider])
        session.flush()
        workspace = Workspace(owner_user_id=owner.id, name="RLS boundary")
        session.add(workspace)
        session.flush()
        projects = [
            Project(workspace_id=workspace.id, name=name, budget_limit=0, aspect_ratio="9:16")
            for name in ("First", "Second")
        ]
        connection = ProviderConnection(
            workspace_id=workspace.id, provider_type="openai_compatible_media",
            display_name="No auth", base_url="https://example.invalid",
            protocol_profile="openai_images_v1", auth_mode="none",
            created_by=owner.id, updated_by=owner.id,
        )
        session.add_all([*projects, connection])
        session.flush()
        revision = ProviderConnectionRevision(
            connection_id=connection.id, revision_no=1,
            provider_type=connection.provider_type, protocol_profile=connection.protocol_profile,
            auth_mode="none", base_url=connection.base_url,
        )
        assets = [Asset(project_id=project.id, kind="character", name="Lead")
                  for project in projects]
        extra_foreign_asset = Asset(project_id=projects[1].id, kind="character", name="Other")
        tag = AssetTag(project_id=projects[0].id, name="lead", normalized_name="lead")
        session.add_all([revision, *assets, extra_foreign_asset, tag])
        session.flush()
        evidence = ProviderAvailabilityEvidence(
            workspace_id=workspace.id, connection_id=connection.id,
            connection_revision_id=revision.id, remote_model_id="model",
            verifier_kind="model_list", status="visible",
        )
        session.add(evidence)
        session.flush()
        availability = ProviderModelAvailability(
            workspace_id=workspace.id, connection_id=connection.id,
            connection_revision_id=revision.id, remote_model_id="model",
            latest_evidence_id=evidence.id, effective_status="visible",
        )
        # Deliberately seed a malformed historical junction using the admin role.
        session.add_all([availability, AssetTagLink(asset_id=assets[0].id, tag_id=tag.id),
                         AssetTagLink(asset_id=assets[1].id, tag_id=tag.id)])
        session.commit()

    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE dramaforge_app"))
        conn.execute(text("SELECT set_config('app.current_workspace_id', :w, true), "
                          "set_config('app.current_project_id', :p, true), "
                          "set_config('app.current_user_id', :u, true)"),
                     {"w": str(workspace.id), "p": str(projects[0].id), "u": str(owner.id)})
        for row in (evidence, availability):
            table = row.__tablename__
            assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE id = :id"),
                                {"id": row.id}).scalar_one() == 1
        assert conn.execute(text("SELECT asset_id FROM asset_tag_links WHERE tag_id = :tag"),
                            {"tag": tag.id}).scalars().all() == [assets[0].id]
        assert conn.execute(text("DELETE FROM asset_tag_links WHERE asset_id = :asset"),
                            {"asset": assets[1].id}).rowcount == 0
        with pytest.raises(DBAPIError) as denied, conn.begin_nested():
            conn.execute(text("INSERT INTO asset_tag_links(asset_id, tag_id) VALUES (:a, :t)"),
                         {"a": extra_foreign_asset.id, "t": tag.id})
        assert denied.value.orig.sqlstate == "42501"

        # Knowledge of another workspace's ID must not be an access grant.
        conn.execute(text("SELECT set_config('app.current_user_id', :u, true)"),
                     {"u": str(outsider.id)})
        for row in (evidence, availability):
            table = row.__tablename__
            assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE id = :id"),
                                {"id": row.id}).scalar_one() == 0
            if table == "provider_model_availability":
                assert conn.execute(text(
                    f"UPDATE {table} SET effective_status = 'not_visible' WHERE id = :id"
                ), {"id": row.id}).rowcount == 0
            with pytest.raises(DBAPIError) as denied, conn.begin_nested():
                # Copy the known row through VALUES, not an RLS-filtered SELECT.
                values = {
                    "id": uuid.uuid4(), "w": workspace.id, "c": connection.id,
                    "r": revision.id, "e": evidence.id,
                }
                if table == "provider_availability_evidence":
                    conn.execute(text(
                        f"INSERT INTO {table}(id, workspace_id, connection_id, "
                        "connection_revision_id, remote_model_id, verifier_kind, status) "
                        "VALUES (:id, :w, :c, :r, 'other', 'model_list', 'visible')"
                    ), values)
                else:
                    conn.execute(text(
                        f"INSERT INTO {table}(id, workspace_id, connection_id, "
                        "connection_revision_id, remote_model_id, latest_evidence_id, "
                        "effective_status) VALUES (:id, :w, :c, :r, 'other', :e, 'visible')"
                    ), values)
            assert denied.value.orig.sqlstate == "42501"


def test_20261030_0095_hardens_rls_and_invariants() -> None:
    dbname = "hardening_" + uuid.uuid4().hex[:12]
    try:
        asyncio.run(_create_db(dbname))
        _alembic(dbname, "upgrade", "head")
        engine = create_engine(_db_sync_url(dbname))
        try:
            _assert_schema_invariants(engine)
            _assert_rls_enforces_both_ownership_boundaries(engine)
        finally:
            engine.dispose()
        _assert_null_project_profile_name_is_unique(dbname)

        _alembic(dbname, "downgrade", "20261030_0094")
        _alembic(dbname, "upgrade", "head")
    finally:
        asyncio.run(_drop_db(dbname))
