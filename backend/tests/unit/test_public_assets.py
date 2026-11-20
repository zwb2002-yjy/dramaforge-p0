"""Public asset publications and project fixed links (I5-01)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Asset, AssetVersion, AssetVersionReference
from app.assets.public_assets import (
    ProjectPublicAssetLinkService,
    PublicAssetConflictError,
    PublicAssetService,
    PublicDisplay,
)
from app.execution.models import Artifact
from test_director_turn_api import api as api


async def _seed_asset(session, *, project: Project, owner: User) -> tuple[AssetVersion, Artifact]:
    artifact = Artifact(
        project_id=project.id,
        artifact_type="image",
        object_key=f"tmp/{uuid4().hex}.png",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
        storage_state="available",
        byte_size=16,
        width=1024,
        height=768,
    )
    session.add(artifact)
    await session.flush()
    asset = Asset(
        project_id=project.id,
        kind="character",
        name="古桥匠人",
        description="",
        status="active",
        version=1,
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        project_id=project.id,
        asset_id=asset.id,
        version_number=1,
        kind="character",
        name="古桥匠人",
        description="",
        status="formal",
        created_by=owner.id,
    )
    session.add(version)
    await session.flush()
    asset.current_version_id = version.id
    session.add(
        AssetVersionReference(
            project_id=project.id,
            asset_version_id=version.id,
            artifact_id=artifact.id,
            reference_role="primary",
            label="primary",
            sort_order=0,
        )
    )
    await session.commit()
    return version, artifact


@pytest.fixture
async def world(session):
    owner = User(email=f"pub-{uuid4()}@example.com", display_name="P", password_hash="x")
    session.add(owner)
    await session.flush()
    workspace = Workspace(name="Public", owner_user_id=owner.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    version, _artifact = await _seed_asset(session, project=project, owner=owner)
    return {
        "session": session,
        "owner": owner,
        "workspace": workspace,
        "project": project,
        "version": version,
        "service": PublicAssetService(session, actor=owner),
    }


async def test_publish_read_withdraw_and_links(world):
    service = world["service"]
    published = await service.publish(
        world["version"].id,
        display=PublicDisplay(
            name="古桥匠人", description="明代匠人", style_labels=["水墨", "写实"]
        ),
    )
    assert published.status == "available" and published.usable is True
    assert published.safe_name == "古桥匠人"
    assert published.style_labels == ["写实", "水墨"]
    assert published.items[0].media_kind == "image"
    assert published.items[0].role == "primary"
    assert published.items[0].width == 1024
    replay = await service.publish(
        world["version"].id,
        display=PublicDisplay(name="古桥匠人", description="明代匠人", style_labels=["水墨"]),
    )
    assert replay.id == published.id
    rows, total = await service.list(query="古桥")
    assert total == 1 and rows[0].id == published.id
    withdrawn = await service.set_withdrawn(
        published.id, expected_revision=1, withdrawn=True
    )
    assert withdrawn.status == "withdrawn" and withdrawn.usable is False
    with pytest.raises(PublicAssetConflictError) as stale:
        await service.set_withdrawn(published.id, expected_revision=1, withdrawn=False)
    assert stale.value.code == "PUBLIC_ASSET_STALE_REVISION"

    links = ProjectPublicAssetLinkService(
        world["session"], actor=world["owner"], project_id=world["project"].id
    )
    with pytest.raises(PublicAssetConflictError) as unavailable:
        await links.create(
            publication_id=published.id, local_label="主参考", request_key="link-1"
        )
    assert unavailable.value.code == "PUBLIC_ASSET_NOT_AVAILABLE"
    restored = await service.set_withdrawn(
        published.id, expected_revision=2, withdrawn=False
    )
    assert restored.status == "available"
    link, created = await links.create(
        publication_id=published.id, local_label="主参考", request_key="link-1"
    )
    assert created is True and link.availability == "available"
    replay_link, created = await links.create(
        publication_id=published.id, local_label="主参考", request_key="link-1"
    )
    assert created is False and replay_link.id == link.id
    with pytest.raises(PublicAssetConflictError) as duplicate:
        await links.create(
            publication_id=published.id, local_label="另一个", request_key="link-2"
        )
    assert duplicate.value.code == "PUBLIC_LINK_EXISTS"
    detached = await links.patch(link.id, expected_version=1, local_label=None, attached=False)
    assert detached.detached_at is not None
    reattached = await links.patch(link.id, expected_version=2, local_label="新标签", attached=True)
    assert reattached.detached_at is None and reattached.local_label == "新标签"
    active, total = await links.list(active=True)
    assert total == 1 and active[0].id == link.id


def test_public_asset_http_reads_and_links(api):
    import asyncio
    from uuid import UUID

    from app.access.models import Project as ProjectModel
    from app.access.models import User as UserModel
    from app.access.models import Workspace as WorkspaceModel
    from app.shared.db import set_rls_context
    from app.shared.security import CSRF_HEADER
    from test_director_turn_api import _csrf, _project, _register

    client, factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Public")
    csrf = {CSRF_HEADER: _csrf(client)}

    async def seed() -> tuple[str, str]:
        async with factory() as session:
            ws = await session.get(WorkspaceModel, UUID(workspace))
            assert ws is not None
            owner = await session.get(UserModel, ws.owner_user_id)
            assert owner is not None
            session.info["selected_workspace_id"] = UUID(workspace)
            await set_rls_context(
                session,
                user_id=owner.id,
                workspace_id=ws.id,
                project_id=UUID(project),
            )
            project_row = await session.get(ProjectModel, UUID(project))
            assert project_row is not None
            version, _artifact = await _seed_asset(session, project=project_row, owner=owner)
            from app.assets.public_assets import PublicAssetService, PublicDisplay

            published = await PublicAssetService(session, actor=owner).publish(
                version.id,
                display=PublicDisplay(
                    name="古桥匠人", description="明代", style_labels=[]
                ),
            )
            await session.commit()
            return str(published.id), str(version.id)

    publication_id, _version_id = asyncio.run(seed())
    listing = client.get("/api/v1/public-assets")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    detail = client.get(f"/api/v1/public-assets/{publication_id}")
    assert detail.status_code == 200
    assert detail.json()["safe_name"] == "古桥匠人"
    assert detail.json()["items"][0]["media_kind"] == "image"
    items = client.get(f"/api/v1/public-assets/{publication_id}/items")
    assert items.json()["total"] == 1
    base = f"/api/v1/projects/{project}/public-asset-links"
    created = client.post(
        base,
        json={
            "request_key": "link-http-1",
            "publication_id": publication_id,
            "local_label": "主参考",
        },
        headers=csrf,
    )
    assert created.status_code == 201, created.text
    link = created.json()
    replay = client.post(
        base,
        json={
            "request_key": "link-http-1",
            "publication_id": publication_id,
            "local_label": "主参考",
        },
        headers=csrf,
    )
    assert replay.status_code == 200 and replay.json()["id"] == link["id"]
    listing_links = client.get(base).json()
    assert listing_links["total"] == 1
    patched = client.patch(
        f"{base}/{link['id']}",
        json={"expected_version": 1, "attached": False},
        headers=csrf,
    )
    assert patched.status_code == 200 and patched.json()["detached_at"] is not None
    withdrawn = client.patch(
        f"/api/v1/public-assets/{publication_id}",
        json={"expected_revision": 1, "withdrawn": True},
        headers=csrf,
    )
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"


def test_public_content_preview_and_ranges(api, monkeypatch):
    import asyncio
    from uuid import UUID

    from app.access.models import Project as ProjectModel
    from app.access.models import User as UserModel
    from app.access.models import Workspace as WorkspaceModel
    from app.shared.db import set_rls_context
    from app.shared.security import CSRF_HEADER
    from app.storage.minio_store import InMemoryObjectStore
    from test_director_turn_api import _csrf, _project, _register

    client, factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Content")
    csrf = {CSRF_HEADER: _csrf(client)}
    store = InMemoryObjectStore()
    monkeypatch.setattr(
        "app.storage.minio_store.get_object_store", lambda settings=None: store
    )
    payload = b"0123456789abcdef"

    async def seed() -> tuple[str, str]:
        async with factory() as session:
            ws = await session.get(WorkspaceModel, UUID(workspace))
            assert ws is not None
            owner = await session.get(UserModel, ws.owner_user_id)
            assert owner is not None
            session.info["selected_workspace_id"] = UUID(workspace)
            await set_rls_context(
                session,
                user_id=owner.id,
                workspace_id=ws.id,
                project_id=UUID(project),
            )
            project_row = await session.get(ProjectModel, UUID(project))
            assert project_row is not None
            version, artifact = await _seed_asset(
                session, project=project_row, owner=owner
            )
            await store.put_bytes(
                object_key=artifact.object_key, data=payload, mime_type="image/png"
            )
            from app.assets.public_assets import PublicAssetService, PublicDisplay

            published = await PublicAssetService(session, actor=owner).publish(
                version.id,
                display=PublicDisplay(name="古桥匠人", description="", style_labels=[]),
            )
            await session.commit()
            return str(published.id), str(published.items[0].id)

    publication_id, item_id = asyncio.run(seed())
    path = f"/api/v1/public-assets/{publication_id}/items/{item_id}/content"
    full = client.get(path)
    assert full.status_code == 200, full.text
    assert full.content == payload
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["x-content-type-options"] == "nosniff"
    assert full.headers["cache-control"] == "private, no-store"
    head = client.head(path)
    assert head.status_code == 200
    assert head.headers["content-length"] == str(len(payload))
    partial = client.get(path, headers={"Range": "bytes=2-5"})
    assert partial.status_code == 206
    assert partial.content == payload[2:6]
    assert partial.headers["content-range"] == f"bytes 2-5/{len(payload)}"
    invalid = client.get(path, headers={"Range": "bytes=0-1,4-5"})
    assert invalid.status_code == 416
    withdrawn = client.patch(
        f"/api/v1/public-assets/{publication_id}",
        json={"expected_revision": 1, "withdrawn": True},
        headers=csrf,
    )
    assert withdrawn.status_code == 200
    assert client.get(path).status_code == 404


def test_project_use_content_reads_through_the_link(api, monkeypatch):
    import asyncio
    from uuid import UUID

    from app.access.models import Project as ProjectModel
    from app.access.models import User as UserModel
    from app.access.models import Workspace as WorkspaceModel
    from app.shared.db import set_rls_context
    from app.shared.security import CSRF_HEADER
    from app.storage.minio_store import InMemoryObjectStore
    from test_director_turn_api import _csrf, _project, _register

    client, factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Project use")
    csrf = {CSRF_HEADER: _csrf(client)}
    store = InMemoryObjectStore()
    monkeypatch.setattr(
        "app.storage.minio_store.get_object_store", lambda settings=None: store
    )
    payload = b"public-bytes"

    async def seed() -> tuple[str, str]:
        async with factory() as session:
            ws = await session.get(WorkspaceModel, UUID(workspace))
            assert ws is not None
            owner = await session.get(UserModel, ws.owner_user_id)
            assert owner is not None
            session.info["selected_workspace_id"] = UUID(workspace)
            await set_rls_context(
                session,
                user_id=owner.id,
                workspace_id=ws.id,
                project_id=UUID(project),
            )
            project_row = await session.get(ProjectModel, UUID(project))
            assert project_row is not None
            version, artifact = await _seed_asset(
                session, project=project_row, owner=owner
            )
            await store.put_bytes(
                object_key=artifact.object_key, data=payload, mime_type="image/png"
            )
            from app.assets.public_assets import (
                ProjectPublicAssetLinkService,
                PublicAssetService,
                PublicDisplay,
            )

            published = await PublicAssetService(session, actor=owner).publish(
                version.id,
                display=PublicDisplay(name="古桥匠人", description="", style_labels=[]),
            )
            link, _created = await ProjectPublicAssetLinkService(
                session, actor=owner, project_id=project_row.id
            ).create(
                publication_id=published.id,
                local_label="项目参考",
                request_key="project-use-link",
            )
            await session.commit()
            return str(link.id), str(published.items[0].id)

    link_id, item_id = asyncio.run(seed())
    path = (
        f"/api/v1/projects/{project}/public-asset-links/{link_id}/items/{item_id}/content"
    )
    full = client.get(path)
    assert full.status_code == 200, full.text
    assert full.content == payload
    partial = client.get(path, headers={"Range": "bytes=0-5"})
    assert partial.status_code == 206
    assert partial.content == payload[:6]
    detached = client.patch(
        f"/api/v1/projects/{project}/public-asset-links/{link_id}",
        json={"expected_version": 1, "attached": False},
        headers=csrf,
    )
    assert detached.status_code == 200
    assert client.get(path).status_code == 404


async def test_public_reference_token_records_identity_and_respects_withdrawal(world):

    from app.config import Settings
    from app.providers.reference_delivery import (
        issue_artifact_reference,
        resolve_public_reference,
    )
    from app.shared.errors import NotFoundError

    service = world["service"]
    published = await service.publish(
        world["version"].id,
        display=PublicDisplay(name="古桥匠人", description="", style_labels=[]),
    )
    links = ProjectPublicAssetLinkService(
        world["session"], actor=world["owner"], project_id=world["project"].id
    )
    link, _created = await links.create(
        publication_id=published.id, local_label="参考", request_key="token-link"
    )
    item_id = published.items[0].id
    artifact_id = (
        await world["session"].get(Artifact, published.items[0].id)
    )
    del artifact_id
    from app.assets.models import AssetVersionReference
    from sqlalchemy import select as sql_select

    artifact = await world["session"].scalar(
        sql_select(AssetVersionReference).where(
            AssetVersionReference.asset_version_id == world["version"].id
        )
    )
    assert artifact is not None
    grant = await issue_artifact_reference(
        world["session"],
        artifact=await world["session"].get(Artifact, artifact.artifact_id),
        workspace_id=world["workspace"].id,
        created_by_user_id=world["owner"].id,
        settings=Settings(
            app_env="test",
            reference_public_base_url="https://references.example",
            reference_token_ttl_seconds=60,
        ),
        publication_id=published.id,
        publication_item_id=item_id,
        public_asset_link_id=link.id,
        owner_user_id=world["owner"].id,
    )
    token = grant.url.rsplit("/", 1)[-1]
    from app.assets.source_use import SourceUseService

    with pytest.raises(NotFoundError):
        await resolve_public_reference(world["session"], token=token)
    uses = SourceUseService(world["session"], actor=world["owner"], project=world["project"])
    await uses.declare(
        artifact_id=artifact.artifact_id,
        allowed_uses=["external_processing", "library_reference"],
        statement="合成样例许可",
        expected_version=0,
        request_key="public-token-use",
    )
    resolved = await resolve_public_reference(world["session"], token=token)
    assert resolved.publication_id == published.id
    assert resolved.publication_item_id == item_id
    assert resolved.public_asset_link_id == link.id
    await service.set_withdrawn(published.id, expected_revision=1, withdrawn=True)
    with pytest.raises(NotFoundError):
        await resolve_public_reference(world["session"], token=token)
