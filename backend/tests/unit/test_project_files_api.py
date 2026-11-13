"""HTTP source lifecycle through the real durable background processing entry."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.access.models import User, Workspace
from app.api.v1 import project_files
from app.assets.project_files import ProjectFileService
from app.shared.security import CSRF_HEADER
from app.storage.minio_store import InMemoryObjectStore
from app.workers import project_files as source_worker
from app.workers.project_files import process_project_files
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


def test_http_upload_background_extract_versions_unlink_and_scope(api, monkeypatch):
    client, factory = api
    store = InMemoryObjectStore()
    monkeypatch.setattr(project_files, "get_object_store", lambda: store)
    workspace = _register(client)
    project = _project(client, workspace, "Sources")
    other = _project(client, workspace, "Other sources")
    path = f"/api/v1/projects/{project}/files"
    query = {"filename": "地方志.txt", "request_key": "upload-once"}
    original = "古桥\n\n年代待核实".encode()
    assert client.post(path, params=query, content=original).status_code == 403
    response = client.post(
        path, params=query, content=original, headers={CSRF_HEADER: _csrf(client)}
    )
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["status"] == "pending" and source["source_available"]
    assert "object_key" not in source and "excerpts" not in source
    revision_path = f"/api/v1/projects/{project}/file-revisions/{source['revision_id']}"
    assert client.get(f"/api/v1/projects/{other}/files/{source['id']}").status_code == 404
    assert client.get(revision_path.replace(project, other)).status_code == 404
    assert asyncio.run(process_project_files(factory, store=store)) == {"processed": 1, "failed": 0}
    # A new scanner invocation models a restarted worker: no completed work is redone.
    assert asyncio.run(process_project_files(factory, store=store)) == {"processed": 0, "failed": 0}
    excerpts = client.get(revision_path, params={"limit": 1}).json()
    assert excerpts["total"] == 2 and excerpts["next_offset"] == 1
    assert excerpts["excerpts"][0]["location"] == {"line": 1}
    assert client.get(revision_path, params={"offset": 1}).json()["excerpts"][0]["location"] == {
        "line": 3,
    }
    downloaded = client.get(revision_path + "/original")
    assert (
        downloaded.content == original and downloaded.headers["x-content-type-options"] == "nosniff"
    )
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    replay = client.post(path, params=query, content=original, headers={CSRF_HEADER: _csrf(client)})
    assert replay.json()["revision_id"] == source["revision_id"]
    changed = client.post(
        path,
        params={**query, "request_key": "update", "file_id": source["id"], "expected_version": 1},
        content=b"Updated original",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["content_version"] == 2
    assert client.get(revision_path + "/original").content == original
    assert (
        client.delete(
            path + "/" + source["id"],
            params={"expected_version": 1},
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 409
    )
    detached = client.delete(
        path + "/" + source["id"],
        params={"expected_version": 2},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert detached.status_code == 200 and not detached.json()["source_available"]
    assert client.get(path).json() == []
    assert not client.get(revision_path).json()["source"]["source_available"]
    assert client.get(revision_path + "/original").status_code == 404
    assert asyncio.run(process_project_files(factory, store=store)) == {"processed": 0, "failed": 0}


def test_storage_failure_is_per_file_retry_is_fenced_and_upload_is_bounded(api, monkeypatch):
    client, factory = api
    store = InMemoryObjectStore()
    monkeypatch.setattr(project_files, "get_object_store", lambda: store)
    workspace = _register(client)
    project = _project(client, workspace, "Recovery")
    path = f"/api/v1/projects/{project}/files"

    def upload(key, data):
        response = client.post(
            path,
            params={"filename": "source.txt", "request_key": key},
            content=data,
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 201, response.text
        return response.json()

    broken = upload("broken", b"temporarily missing")
    good = upload("good", b"good original")
    key = f"projects/{project}/sources/{broken['content_hash']}"
    asyncio.run(store.delete_bytes(object_key=key))
    counts = asyncio.run(process_project_files(factory, store=store))
    assert counts == {"processed": 1, "failed": 1}
    assert client.get(path + "/" + good["id"]).json()["status"] == "parsed"
    failed = client.get(path + "/" + broken["id"]).json()
    assert failed["error_code"] == "source_processing_failed"
    asyncio.run(
        store.put_bytes(object_key=key, data=b"temporarily missing", mime_type="text/plain")
    )
    retry_path = f"/api/v1/projects/{project}/file-revisions/{broken['revision_id']}/retry"
    retried = client.post(
        retry_path, json={"request_key": "retry-once"}, headers={CSRF_HEADER: _csrf(client)}
    )
    assert retried.status_code == 200 and retried.json()["attempt"] == 2

    async def old_worker_result():
        async with factory() as session:
            ws = await session.get(Workspace, UUID(workspace))
            actor = await session.get(User, ws.owner_user_id)
            session.info["selected_workspace_id"] = UUID(workspace)
            service = ProjectFileService(
                session, store=store, actor=actor, project_id=UUID(project)
            )
            await service.fail_extraction(UUID(broken["revision_id"]), expected_attempt=1)
            row = await service.extract(UUID(broken["revision_id"]), expected_attempt=1)
            assert row.status == "pending" and row.attempt == 2 and row.excerpts == []
            await session.commit()

    asyncio.run(old_worker_result())
    assert asyncio.run(process_project_files(factory, store=store))["processed"] == 1
    replay = client.post(
        retry_path, json={"request_key": "retry-once"}, headers={CSRF_HEADER: _csrf(client)}
    )
    assert replay.json()["attempt"] == 2 and replay.json()["status"] == "parsed"
    monkeypatch.setattr(project_files, "MAX_SOURCE_BYTES", 2)
    oversized = client.post(
        path,
        params={"filename": "large.txt", "request_key": "large"},
        content=b"too large",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert oversized.status_code == 413


def test_blocked_failure_receipt_does_not_starve_later_files(api, monkeypatch):
    client, factory = api
    store = InMemoryObjectStore()
    monkeypatch.setattr(project_files, "get_object_store", lambda: store)
    workspace = _register(client)
    project = _project(client, workspace, "Blocked source")
    path = f"/api/v1/projects/{project}/files"
    rows = []
    originals = {}
    for key in ("first", "second", "third"):
        response = client.post(
            path,
            params={"filename": "source.txt", "request_key": key},
            content=key.encode(),
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 201
        rows.append(response.json())
        originals[rows[-1]["content_hash"]] = key.encode()
    rows.sort(key=lambda row: row["revision_id"])
    missing_key = f"projects/{project}/sources/{rows[0]['content_hash']}"
    asyncio.run(store.delete_bytes(object_key=missing_key))

    async def blocked_receipt(*args, **kwargs):
        await asyncio.Event().wait()

    with monkeypatch.context() as patch:
        patch.setattr(ProjectFileService, "fail_extraction", blocked_receipt)
        patch.setattr(source_worker, "FAILURE_RECEIPT_TIMEOUT_SECONDS", 0.01)
        cursor = source_worker.SourceScanCursor()
        counts = [
            asyncio.run(process_project_files(factory, store=store, limit=1, cursor=cursor))
            for _ in range(3)
        ]
        assert counts == [
            {"processed": 0, "failed": 1},
            {"processed": 1, "failed": 0},
            {"processed": 1, "failed": 0},
        ]
        assert asyncio.run(process_project_files(factory, store=store, limit=1, cursor=cursor)) == {
            "processed": 0,
            "failed": 0,
        }
        assert cursor.after_revision_id is None
    assert client.get(path + "/" + rows[0]["id"]).json()["status"] == "pending"
    assert client.get(path + "/" + rows[1]["id"]).json()["status"] == "parsed"
    assert client.get(path + "/" + rows[2]["id"]).json()["status"] == "parsed"
    asyncio.run(
        store.put_bytes(
            object_key=missing_key, data=originals[rows[0]["content_hash"]], mime_type="text/plain"
        )
    )
    assert asyncio.run(process_project_files(factory, store=store)) == {"processed": 1, "failed": 0}
