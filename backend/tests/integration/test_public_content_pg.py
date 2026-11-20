"""Both browser content paths use current permissions, even across Owner workspaces."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.public_assets import (
    ProjectPublicAssetLinkService,
    PublicAssetService,
    PublicDisplay,
)
from app.assets.source_use import SourceUseService
from app.execution.models import Artifact
from app.shared.db import set_rls_context
from app.storage.minio_store import reset_object_store_for_tests
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import _async_url
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

from fixtures.public_asset_seed import _seed_asset


@pytest.mark.parametrize("change", ["direct_revocation", "upstream_revocation", "soft_delete"])
async def test_public_content_rechecks_before_storage(http_agent, monkeypatch, change):
    agent = http_agent
    engine = create_async_engine(_async_url(agent.database.name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = reset_object_store_for_tests()
    payload = b"0123456789abcdef"
    accesses = []

    def counted(method):
        original = getattr(store, method)

        async def observe(**kwargs):
            accesses.append(method)
            return await original(**kwargs)

        return observe

    for method in ("get_bytes", "get_size", "get_range"):
        monkeypatch.setattr(store, method, counted(method))

    try:
        async with factory() as db:
            source = await db.get(Project, agent.project_id)
            ws = await db.get(Workspace, source.workspace_id)
            owner = await db.get(User, ws.owner_user_id)
            dest = Project(
                workspace_id=agent.other_workspace_id,
                name="Consumer",
                aspect_ratio="16:9",
                budget_limit=0,
                work_type="single_comic",
            )
            db.add(dest)
            await db.flush()
            version, artifact = await _seed_asset(db, project=source, owner=owner)
            await store.put_bytes(
                object_key=artifact.object_key, data=payload, mime_type="image/png"
            )
            publication = await PublicAssetService(db, actor=owner).publish(
                version.id, display=PublicDisplay(name="Fixture", description="", style_labels=[])
            )
            db.info["selected_workspace_id"] = dest.workspace_id
            link, _ = await ProjectPublicAssetLinkService(
                db, actor=owner, project_id=dest.id
            ).create(publication_id=publication.id, local_label="Fixture", request_key="attach")
            await db.commit()
        item = publication.items[0].id
        paths = [
            f"/api/v1/public-assets/{publication.id}/items/{item}/content",
            f"/api/v1/projects/{dest.id}/public-asset-links/{link.id}/items/{item}/content",
        ]
        headers = {"X-Workspace-Id": str(dest.workspace_id)}

        async def denied(url):
            before = list(accesses)
            for method, extra in [("GET", {}), ("GET", {"Range": "bytes=1-3"}), ("HEAD", {})]:
                r = await agent.client.request(method, url, headers={**headers, **extra})
                assert r.status_code == 404, (method, r.status_code)
                assert "object_key" not in r.text
            assert accesses == before

        for url in paths:
            await denied(url)  # Publication alone does not grant the library use.

        async with factory() as db:
            uses = SourceUseService(db, project=source, actor=owner)
            grant = await uses.declare(
                artifact_id=artifact.id,
                allowed_uses=["library_reference"],
                statement="Synthetic library use",
                request_key="direct",
            )
            if change == "upstream_revocation":
                # The item directly allows library use. All of its inputs must also allow it.
                child = artifact
                for level in (1, 2):
                    upstream = Artifact(
                        project_id=source.id,
                        artifact_type="image",
                        storage_state="available",
                        object_key=f"fixture/input-{uuid4()}.png",
                        content_hash=uuid4().hex * 2,
                        byte_size=16,
                        mime_type="image/png",
                    )
                    db.add(upstream)
                    await db.flush()
                    grant = await uses.declare(
                        artifact_id=upstream.id,
                        allowed_uses=["library_reference"],
                        statement="Synthetic inherited use",
                        request_key=f"upstream-{level}",
                    )
                    await uses.record_artifact_source_use(
                        artifact_id=child.id,
                        source_subject_id=grant.subject_id,
                        source_project_id=source.id,
                        source_revision_id=grant.id,
                        consumer_node_run_id=uuid4(),
                        input_role="visual",
                    )
                    child = upstream
            await db.commit()
        if change == "soft_delete":
            async with factory() as db:
                archived = await db.get(Project, source.id)
                archived.deleted_at = datetime.now(UTC)
                await db.commit()
        # Prove the positive response did not rely on the API role seeing private artifacts.
        async with agent.factory() as db:
            assert await db.scalar(text("SELECT current_user")) == "dramaforge_app"
            await set_rls_context(
                db, user_id=owner.id, workspace_id=dest.workspace_id, project_id=dest.id
            )
            assert await db.scalar(select(Artifact.id).where(Artifact.id == artifact.id)) is None
        for url in paths:
            head = await agent.client.head(url, headers=headers)
            assert head.status_code == 200 and head.headers["Content-Length"] == str(len(payload))
            assert (await agent.client.get(url, headers=headers)).content == payload
            partial = await agent.client.get(url, headers={**headers, "Range": "bytes=1-3"})
            assert partial.status_code == 206 and partial.content == payload[1:4]
        assert accesses == ["get_bytes", "get_range"] * 2
        await denied(paths[0].replace(str(item), str(uuid4())))
        await denied(paths[1].replace(str(link.id), str(uuid4())))
        if change == "direct_revocation":
            import httpx

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=agent.app), base_url="http://testserver"
            ) as outsider:
                reg = await outsider.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"other-{uuid4()}@example.com",
                        "password": "Synthetic-owner-2026",
                        "display_name": "Other owner",
                    },
                )
                assert reg.status_code == 201, reg.text
                own = (await outsider.get("/api/v1/workspaces")).json()[0]["id"]
                before = list(accesses)
                for url in paths:
                    assert (
                        await outsider.get(url, headers={"X-Workspace-Id": own})
                    ).status_code == 404
                assert accesses == before
        async with factory() as db:
            if change == "soft_delete":
                row = await db.get(Artifact, artifact.id)
                # A still-available storage_state must not override the soft deletion.
                row.deleted_at = datetime.now(UTC)
            else:
                await SourceUseService(db, project=source, actor=owner).declare(
                    artifact_id=upstream.id if change == "upstream_revocation" else artifact.id,
                    expected_version=grant.result_version,
                    state="revoked",
                    allowed_uses=[],
                    statement="",
                    request_key="revoke",
                )
            await db.commit()
        for url in paths:
            await denied(url)
    finally:
        await engine.dispose()
