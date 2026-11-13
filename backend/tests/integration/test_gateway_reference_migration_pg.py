"""Written connection/revision references must survive rollback attempts."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from test_director_turn_lifecycle_pg import _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


@pytest.mark.parametrize(
    "written_table", ["provider_connections", "provider_connection_revisions", None]
)
async def test_gateway_downgrade_refuses_any_written_reference(written_table):
    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/20261027_0089_gateway_references.py"
    )
    spec = importlib.util.spec_from_file_location("gateway_reference_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    dbname = "gateway_downgrade_" + uuid4().hex[:12]
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        async with engine.begin() as connection:
            # Temporary tables shadow only this isolated session. No production
            # schema or migrated business snapshot is edited to stage the test.
            for table in ("provider_connections", "provider_connection_revisions"):
                await connection.execute(
                    text(f"CREATE TEMP TABLE {table} (id integer, gateway_ref json)")
                )
            if written_table:
                await connection.execute(
                    text(
                        f'INSERT INTO {written_table} VALUES (1, \'{{"deployment_id":"fixture"}}\')'
                    )
                )

            def downgrade(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.downgrade()

            if written_table:
                with pytest.raises(RuntimeError, match="GATEWAY_REFERENCE_DOWNGRADE_BLOCKED"):
                    await connection.run_sync(downgrade)
                assert (
                    await connection.scalar(
                        text(f"SELECT count(*) FROM {written_table} WHERE gateway_ref IS NOT NULL")
                    )
                    == 1
                )
            else:
                await connection.run_sync(downgrade)
                columns = await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_attribute "
                        "WHERE attrelid='pg_temp.provider_connections'::regclass "
                        "AND attname='gateway_ref' AND NOT attisdropped"
                    )
                )
                assert columns == 0
    finally:
        await engine.dispose()
        await _drop_database(dbname)
