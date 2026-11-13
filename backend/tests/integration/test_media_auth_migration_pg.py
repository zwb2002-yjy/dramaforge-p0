"""No-auth migration preserves bearer rows and refuses destructive rollback."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from test_director_turn_lifecycle_pg import _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


@pytest.mark.parametrize("retain_no_auth", [False, True])
async def test_media_auth_upgrade_and_guarded_rollback(retain_no_auth):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261027_0090_media_auth_mode.py"
    spec = importlib.util.spec_from_file_location("media_auth_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    dbname = "media_auth_" + uuid4().hex[:12]
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    credential = uuid4()
    revision = uuid4()
    try:
        async with engine.begin() as connection:
            for table, column in (
                ("provider_connections", "credential_id"),
                ("provider_connection_revisions", "credential_revision_id"),
            ):
                await connection.execute(
                    text(
                        f"CREATE TEMP TABLE {table} (id integer, provider_type text, "
                        f"{column} uuid NOT NULL)"
                    )
                )
                await connection.execute(
                    text(f"INSERT INTO {table} VALUES (1, 'agnes', :credential)"),
                    {"credential": credential},
                )
            for table in ("provider_availability_evidence", "provider_model_availability"):
                await connection.execute(
                    text(
                        f"CREATE TEMP TABLE {table} (connection_revision_id uuid, "
                        "credential_revision_id uuid NOT NULL, remote_model_id text)"
                    )
                )
            await connection.execute(
                text(
                    "ALTER TABLE provider_model_availability ADD CONSTRAINT "
                    "uq_provider_model_availability_identity UNIQUE "
                    "(connection_revision_id, credential_revision_id, remote_model_id)"
                )
            )

            def run(sync_connection, action):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    getattr(migration, action)()

            await connection.run_sync(run, "upgrade")
            for table, column in (
                ("provider_connections", "credential_id"),
                ("provider_connection_revisions", "credential_revision_id"),
            ):
                rows = (
                    await connection.execute(text(f"SELECT {column}, auth_mode FROM {table}"))
                ).all()
                assert rows == [(credential, "bearer")]
                for invalid in (
                    "(2, 'agnes', NULL, 'bearer')",
                    "(2, 'agnes', NULL, 'none')",
                    f"(2, 'openai_compatible_media', '{credential}', 'none')",
                ):
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(text(f"INSERT INTO {table} VALUES {invalid}"))
                if retain_no_auth:
                    await connection.execute(
                        text(
                            f"INSERT INTO {table} "
                            "VALUES (2, 'openai_compatible_media', NULL, 'none')"
                        )
                    )
            if retain_no_auth:
                statement = text(
                    "INSERT INTO provider_model_availability "
                    "VALUES (:revision, NULL, 'configured-id')"
                )
                await connection.execute(statement, {"revision": revision})
                with pytest.raises(IntegrityError):
                    async with connection.begin_nested():
                        await connection.execute(statement, {"revision": revision})
                with pytest.raises(RuntimeError, match="MEDIA_AUTH_DOWNGRADE_BLOCKED"):
                    await connection.run_sync(run, "downgrade")
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM provider_connection_revisions "
                            "WHERE auth_mode='none'"
                        )
                    )
                    == 1
                )
            else:
                await connection.run_sync(run, "downgrade")
                assert (
                    await connection.scalar(text("SELECT credential_id FROM provider_connections"))
                    == credential
                )
    finally:
        await engine.dispose()
        await _drop_database(dbname)
