"""An existing Provider URL obeys committed source declarations at read time."""

from uuid import uuid4

import pytest
from app.api.v1.provider_references import provider_reference_get, provider_reference_head
from app.assets.source_use import SourceUseService
from app.config import Settings
from app.execution.models import Artifact, NodeRun
from app.providers.reference_delivery import issue_artifact_reference
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError
from app.storage.minio_store import get_object_store
from sqlalchemy import select, text
from starlette.requests import Request
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark

from fixtures.final_film_seed import _seed_renderable_final_film


@pytest.mark.parametrize("public", [False, True], ids=["private", "published"])
async def test_token_rechecks_source_lineage_before_object_io(pg_session, monkeypatch, public):
    db = pg_session
    project, owner, _, _, videos = await _seed_renderable_final_film(db)
    source = videos[0]
    consumer = (await db.scalars(select(NodeRun).where(NodeRun.project_id == project.id))).first()
    assert consumer is not None
    store = get_object_store()
    data = b"synthetic derivative"
    blob = await store.put_bytes(object_key=f"fixture/{uuid4()}", data=data, mime_type="image/png")
    derived = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="available",
        object_key=blob.object_key,
        content_hash=blob.content_hash,
        byte_size=blob.byte_size,
        mime_type=blob.mime_type,
        produced_by_run_id=consumer.id,
    )
    db.add(derived)
    await db.flush()
    service = SourceUseService(db, project=project, actor=owner)
    declaration = await service.declare(
        artifact_id=source.id,
        expected_version=0,
        state="declared",
        allowed_uses=["external_processing", "library_reference"],
        statement="Synthetic fixture",
        request_key="permit",
    )
    await service.record_artifact_source_use(
        artifact_id=derived.id,
        source_subject_id=declaration.subject_id,
        source_project_id=project.id,
        source_revision_id=declaration.id,
        consumer_node_run_id=consumer.id,
        input_role="test",
    )
    reference_scope = {}
    if public:
        from app.assets.models import Asset, AssetVersion, AssetVersionReference
        from app.assets.public_assets import (
            ProjectPublicAssetLinkService,
            PublicAssetService,
            PublicDisplay,
        )

        asset = Asset(
            project_id=project.id, kind="image", name="Fixture", description="", status="active"
        )
        db.add(asset)
        await db.flush()
        version = AssetVersion(
            project_id=project.id,
            asset_id=asset.id,
            version_number=1,
            kind="image",
            name="Fixture",
            description="",
            status="formal",
            created_by=owner.id,
        )
        db.add(version)
        await db.flush()
        asset.current_version_id = version.id
        db.add(
            AssetVersionReference(
                project_id=project.id,
                asset_version_id=version.id,
                artifact_id=derived.id,
                reference_role="primary",
                label="",
                sort_order=0,
            )
        )
        await db.flush()
        db.info["selected_workspace_id"] = project.workspace_id
        await set_rls_context(
            db, user_id=owner.id, workspace_id=project.workspace_id, project_id=project.id,
        )
        publication = await PublicAssetService(db, actor=owner).publish(
            version.id, display=PublicDisplay(name="Fixture", description="", style_labels=[])
        )
        link, _ = await ProjectPublicAssetLinkService(
            db, actor=owner, project_id=project.id
        ).create(publication_id=publication.id, local_label="Fixture", request_key="link")
        reference_scope = {
            "publication_id": publication.id,
            "publication_item_id": publication.items[0].id,
            "public_asset_link_id": link.id,
            "owner_user_id": owner.id,
        }
    grant = await issue_artifact_reference(
        db,
        artifact=derived,
        workspace_id=project.workspace_id,
        created_by_user_id=owner.id,
        **reference_scope,
        settings=Settings(
            app_env="test",
            reference_public_base_url="https://references.example",
            reference_token_ttl_seconds=600,
        ),
    )
    token = grant.url.rsplit("/", 1)[1]
    await db.commit()
    reads = []
    original = store.get_bytes

    async def counted(*, object_key):
        reads.append(object_key)
        return await original(object_key=object_key)

    monkeypatch.setattr(store, "get_bytes", counted)

    def req(method):
        return Request({"type": "http", "method": method, "path": "/reference", "headers": []})

    await db.execute(text("SET LOCAL ROLE dramaforge_app"))
    assert (await provider_reference_get(token, req("GET"), db)).body == data
    await db.commit()
    assert reads == [blob.object_key]
    await service.declare(
        artifact_id=source.id,
        expected_version=declaration.result_version,
        state="revoked",
        allowed_uses=[],
        statement="",
        request_key="withdraw",
    )
    await db.commit()
    await db.execute(text("SET LOCAL ROLE dramaforge_app"))
    for method, handler in [("GET", provider_reference_get), ("HEAD", provider_reference_head)]:
        with pytest.raises(NotFoundError):
            await handler(token, req(method), db)
    assert reads == [blob.object_key]
