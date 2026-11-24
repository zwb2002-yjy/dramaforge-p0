"""A public clip is authorized separately at save, export, queue and use."""

import hashlib
import json
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Shot
from app.assets.public_assets import (
    ProjectPublicAssetLinkService,
    PublicAssetService,
    PublicDisplay,
)
from app.assets.source_use import SourceUseService
from app.delivery.models import Export
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.edit_session_render import execute_edit_session_render
from app.shared.db import set_node_run_rls_context
from app.shared.errors import ValidationAppError
from app.storage.minio_store import reset_object_store_for_tests
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import _async_url
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

from fixtures.public_asset_seed import _seed_asset


@pytest.mark.parametrize("kind", ["video", "audio"])
async def test_edit_public_material_rechecks_at_each_entry(http_agent, monkeypatch, kind):
    agent = http_agent
    engine = create_async_engine(_async_url(agent.database.name))
    admin = async_sessionmaker(engine, expire_on_commit=False)
    store = reset_object_store_for_tests()
    reads = []
    original = store.iter_bytes

    async def observed(**kwargs):
        reads.append(kwargs["object_key"])
        async for part in original(**kwargs):
            yield part

    monkeypatch.setattr(store, "iter_bytes", observed)
    try:
        async with admin() as db:
            dest = await db.get(Project, agent.project_id)
            ws = await db.get(Workspace, agent.workspace_id)
            owner = await db.get(User, ws.owner_user_id)
            source = Project(workspace_id=agent.other_workspace_id, name="Source",
                             aspect_ratio="16:9", budget_limit=0)
            db.add(source)
            await db.flush()
            version, media = await _seed_asset(db, project=source, owner=owner)
            media.artifact_type = kind
            media.mime_type = "video/mp4" if kind == "video" else "audio/mpeg"
            blob = await store.put_bytes(object_key=media.object_key, data=b"synthetic input",
                                         mime_type=media.mime_type)
            media.content_hash, media.byte_size = blob.content_hash, blob.byte_size
            await db.flush()
            subject = media
            if kind == "audio":
                # Change the input's permission while the derived audio stays fully licensed.
                uses = SourceUseService(db, actor=owner, project=source)
                await uses.declare(
                    artifact_id=media.id, allowed_uses=["library_reference", "creation", "export"],
                    statement="Synthetic derivative", request_key="derived",
                )
                subject = Artifact(
                    project_id=source.id, artifact_type="audio", mime_type="audio/mpeg",
                    object_key="fixture/base.mp3", content_hash="a" * 64, byte_size=16,
                    storage_state="available",
                )
                db.add(subject)
                await db.flush()
                basis = await uses.declare(
                    artifact_id=subject.id, allowed_uses=["library_reference"],
                    statement="Synthetic origin", request_key="base",
                )
                await uses.record_artifact_source_use(
                    artifact_id=media.id, source_subject_id=basis.subject_id,
                    source_project_id=source.id, source_revision_id=basis.id,
                    consumer_node_run_id=uuid4(), input_role="audio",
                )
            else:
                basis = await SourceUseService(db, actor=owner, project=source).declare(
                    artifact_id=media.id, allowed_uses=["library_reference"],
                    statement="Synthetic library license", request_key="base",
                )
            publication = await PublicAssetService(db, actor=owner).publish(
                version.id, display=PublicDisplay(name="Clip", description="", style_labels=[]),
            )
            db.info["selected_workspace_id"] = dest.workspace_id
            link, _ = await ProjectPublicAssetLinkService(
                db, actor=owner, project_id=dest.id,
            ).create(publication_id=publication.id, local_label="Clip", request_key="clip")
            public = {
                "kind": "public_material", "public_asset_link_id": str(link.id),
                "publication_id": str(publication.id),
                "publication_item_id": str(publication.items[0].id),
            }
            clip = {"id": "one", "order": 1, "duration_seconds": 1.0, "source": public}
            if kind == "audio":
                base = await store.put_bytes(object_key="fixture/private.mp4", data=b"private",
                                             mime_type="video/mp4")
                video = Artifact(project_id=dest.id, artifact_type="video", mime_type="video/mp4",
                                 object_key=base.object_key, content_hash=base.content_hash,
                                 byte_size=base.byte_size, storage_state="available")
                db.add(video)
                await db.flush()
                shot = await db.get(Shot, agent.shot_id)
                shot.formal_video_artifact_id = video.id
                clip.update(audio_source=public, source={
                    "kind": "shot_formal", "shot_id": str(shot.id), "artifact_id": str(video.id),
                })
            edit = await EditingAdapter(db).create_session(
                project_id=dest.id, user_id=owner.id, name="Cut",
            )
            await db.commit()

        async def permit(uses, version):
            async with admin() as db:
                result = await SourceUseService(db, actor=owner, project=source).declare(
                    artifact_id=subject.id, allowed_uses=uses, expected_version=version,
                    state="declared" if uses else "revoked",
                    statement="Synthetic use", request_key=str(uuid4()),
                )
                await db.commit()
                return result.result_version

        path = f"/api/v1/projects/{dest.id}/edit-sessions/{edit.id}"
        save = {"expected_session_version": 1, "timeline": {"schema_version": 2, "clips": [clip]}}
        receipt = {"format": "mp4", "idempotency_key": "cut"}
        patch = agent.client.patch
        post = agent.client.post
        ver = basis.result_version
        denied_preview = await post(path + "/preview-plan", headers=agent.headers, json=save)
        assert denied_preview.status_code == 422 and not reads
        denied = await patch(path + "/timeline", headers=agent.headers, json=save)
        assert denied.status_code == 422 and "EDIT_SOURCE_NOT_ADOPTED" in denied.text
        ver = await permit(["library_reference", "creation"], ver)
        preview = await post(path + "/preview-plan", headers=agent.headers, json=save)
        assert preview.status_code == 200, preview.text
        playback = preview.json()["clips"][0]
        key = "video" if kind == "video" else "audio"
        assert playback[f"{key}_public_ref"] == {
            "public_asset_link_id": str(link.id),
            "publication_item_id": str(publication.items[0].id),
        }
        assert playback[f"{key}_artifact_id"] is None and str(media.id) not in preview.text
        assert playback["duration_ms"] == 1000 and reads == []
        assert (await agent.client.get(path)).json()["version"] == 1
        saved = await patch(path + "/timeline", headers=agent.headers, json=save)
        assert saved.status_code == 200, saved.text
        denied = await post(path + "/exports", headers=agent.headers, json=receipt)
        assert denied.status_code == 422 and "EDIT_SOURCE_NOT_ADOPTED" in denied.text
        assert (await agent.client.get(path + "/export")).status_code == 422
        ver = await permit(["library_reference", "creation", "export"], ver)
        created = await post(path + "/exports", headers=agent.headers, json=receipt)
        assert created.status_code == 201, created.text
        export_id = UUID(created.json()["id"])
        render = f"/api/v1/projects/{dest.id}/exports/{export_id}/render"
        ver = await permit(["export", "creation"], ver)
        denied = await post(render, headers=agent.headers)
        assert denied.status_code == 422 and "EDIT_SOURCE_NOT_ADOPTED" in denied.text
        ver = await permit(["library_reference", "export"], ver)
        queued = await post(render, headers=agent.headers)
        assert queued.status_code == 200, queued.text
        run_id = UUID(queued.json()["node_run_id"])
        if kind == "audio":
            async with admin() as db:
                # A pre-0126 queue entry only carries instructions, hashes and the timeline digest.
                legacy = await db.get(NodeRun, run_id)
                old = dict(legacy.input_snapshot)
                del old["public_inputs"]
                legacy.input_snapshot = old
                legacy.input_hash = hashlib.sha256(json.dumps(
                    old, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                ).encode()).hexdigest()
                await db.commit()

        async def execute(task):
            async with agent.factory() as db:
                assert await db.scalar(text("SELECT current_user")) == "dramaforge_app"
                await set_node_run_rls_context(db, node_run_id=task)
                assert await db.scalar(select(Artifact.id).where(Artifact.id == media.id)) is None
                run = await db.get(NodeRun, task)
                node = await db.get(GraphNode, run.graph_node_id)
                result = await execute_edit_session_render(db, run=run, node=node, obj_store=store)
                await db.commit()
                return result

        control = await post(path + "/exports", headers=agent.headers, json={
            **receipt, "idempotency_key": "positive-control",
        })
        assert control.status_code == 201, control.text
        control_queue = await post(
            f"/api/v1/projects/{dest.id}/exports/{control.json()['id']}/render",
            headers=agent.headers,
        )
        assert control_queue.status_code == 200, control_queue.text
        result = await execute(UUID(control_queue.json()["node_run_id"]))
        assert result.artifact_id and media.object_key in reads
        before_revocation = list(reads)
        await permit([], ver)
        denied = await patch(
            path + "/timeline", headers=agent.headers,
            json={**save, "expected_session_version": saved.json()["version"]},
        )
        assert denied.status_code == 422 and "EDIT_SOURCE_NOT_ADOPTED" in denied.text
        with pytest.raises(ValidationAppError) as refused:
            await execute(run_id)
        assert refused.value.details["code"] == "EDIT_SOURCE_NOT_ADOPTED"
        assert reads == before_revocation
        async with admin() as db:
            assert (await db.get(Export, export_id)).result_artifact_id is None
    finally:
        await engine.dispose()
