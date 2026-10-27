"""Workspace settings read generation facts through ordinary project RLS."""

from uuid import uuid4

from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.models import GraphVersion, ProductionGraph, definition_hash
from app.providers.connection_service import ProviderConnectionService
from app.providers.models import ProviderConnection
from app.shared.db import set_rls_context
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _seed


async def test_generation_projection_preserves_workspace_request_scope():
    dbname = "binding_generation_" + uuid4().hex[:10]
    await _create_database(dbname)
    _alembic(dbname)
    admin = create_async_engine(_async_url(dbname))
    app = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}}
    )
    try:
        async with async_sessionmaker(admin, expire_on_commit=False)() as db:
            project, binding, user = await _seed(db)
            service = ProviderConnectionService(db)
            connection = await db.get(ProviderConnection, binding.connection_id)
            revision = await service.current_connection_revision(connection=connection)
            graph = ProductionGraph(
                project_id=project.id,
                scope_type="episode",
                scope_entity_id=project.id,
                template_key="generation-evidence",
                status="draft",
                created_by=user.id,
            )
            db.add(graph)
            await db.flush()
            version = GraphVersion(
                graph_id=graph.id,
                version_number=1,
                status="draft",
                definition={"nodes": []},
                definition_hash=definition_hash({"nodes": []}),
            )
            db.add(version)
            await db.flush()
            node = GraphNode(
                graph_version_id=version.id,
                node_key="video",
                node_type="video",
                display_name="Video",
            )
            db.add(node)
            await db.flush()
            run = NodeRun(
                project_id=project.id,
                graph_version_id=version.id,
                graph_node_id=node.id,
                attempt_no=1,
                idempotency_key="generation-evidence",
                input_hash="a" * 64,
                status="queued",
                input_snapshot={},
                created_by=user.id,
            )
            db.add(run)
            await db.flush()
            artifact = Artifact(
                project_id=project.id,
                artifact_type="video",
                storage_state="available",
                object_key="fixture/result.mp4",
                content_hash="b" * 64,
                mime_type="video/mp4",
                byte_size=100,
                produced_by_run_id=run.id,
            )
            db.add(artifact)
            await db.flush()
            run.result_artifact_id = artifact.id
            run.status = "completed"
            db.add(
                ProviderOperation(
                    node_run_id=run.id,
                    operation_kind="video.generate",
                    actual_provider=revision.provider_type,
                    actual_model=binding.invoke_model_value,
                    protocol_profile=revision.protocol_profile,
                    request_fingerprint="c" * 64,
                    connection_id=connection.id,
                    provider_connection_revision_id=revision.id,
                    credential_revision_id=revision.credential_revision_id,
                    model_binding_id=binding.id,
                    catalog_entry_id=binding.catalog_entry_id,
                    capability_manifest_hash=binding.capability_manifest_hash,
                    execution_path_version="unified-v1",
                    status="succeeded",
                )
            )
            await db.commit()
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            await set_rls_context(db, user_id=user.id, workspace_id=project.workspace_id)
            assert await db.scalar(select(NodeRun.id)) is None
            revision_id, ids = await ProviderConnectionService(db).generation_verified_bindings(
                workspace_id=project.workspace_id, connection_id=connection.id
            )
            assert revision_id == revision.id and ids == {binding.id}
            assert (
                await db.scalar(text("SELECT current_setting('app.current_project_id',true)")) == ""
            )
            assert await db.scalar(select(NodeRun.id)) is None
            assert not db.new and not db.dirty and not db.deleted
    finally:
        await app.dispose()
        await admin.dispose()
        await _drop_database(dbname)
