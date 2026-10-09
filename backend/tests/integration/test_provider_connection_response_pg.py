"""Connection write responses must be read while PostgreSQL workspace RLS is active."""

from __future__ import annotations

from uuid import uuid4

from app.access.models import Workspace
from app.api.v1.provider_connections import (
    ConnectionCreate,
    ConnectionPatch,
    CredentialWrite,
    create_connection,
    patch_connection,
    put_connection_credential,
)
from app.providers.models import ProviderConnection
from app.shared.db import set_rls_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from test_phase5_restart_recovery_pg import _project


async def test_connection_create_patch_and_credential_responses_survive_transaction_rls():
    dbname = "dramaforge_connection_response_" + uuid4().hex[:8]
    await _create_database(dbname)
    _alembic(dbname)
    admin = create_async_engine(_async_url(dbname))
    admin_factory = async_sessionmaker(admin, expire_on_commit=False)
    async with admin_factory() as pg_session:
        user, project_id, workspace_id = await _project(pg_session)
        workspace = await pg_session.get(Workspace, workspace_id)
        assert workspace is not None
    engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:

            async def scope():
                await set_rls_context(
                    db, user_id=user.id, workspace_id=workspace_id, project_id=project_id
                )

            await scope()
            created = await create_connection(
                workspace_id=workspace_id,
                body=ConnectionCreate(
                    provider_type="agnes",
                    protocol_profile="agnes_cn_v1",
                    display_name="PG connection",
                    api_key="fixture-secret",
                ),
                workspace=workspace,
                user=user,
                session=db,
                _="controlled",
            )
            assert created.credential_configured and created.connection_revision_id is not None
            # SESSION role remains restricted after commit, while transaction-local scope expires.
            assert (
                await db.scalar(
                    select(ProviderConnection).where(ProviderConnection.id == created.id)
                )
                is None
            )
            await scope()
            patched = await patch_connection(
                workspace_id=workspace_id,
                connection_id=created.id,
                body=ConnectionPatch(display_name="Renamed PG connection"),
                workspace=workspace,
                user=user,
                session=db,
                _="controlled",
            )
            assert patched.display_name == "Renamed PG connection" and patched.credential_configured
            await scope()
            rotated = await put_connection_credential(
                workspace_id=workspace_id,
                connection_id=created.id,
                body=CredentialWrite(api_key="rotated-fixture-secret"),
                workspace=workspace,
                user=user,
                session=db,
                _="controlled",
            )
            assert rotated.connection_revision_id != created.connection_revision_id
            assert rotated.credential_configured
            assert "fixture-secret" not in rotated.model_dump_json()
            await scope()
            connections = (await db.scalars(select(ProviderConnection))).all()
            assert len(connections) == 1
    finally:
        await engine.dispose()
        await admin.dispose()
        await _drop_database(dbname)
