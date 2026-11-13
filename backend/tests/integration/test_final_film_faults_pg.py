"""Real PG + MinIO crash/network/concurrent cleanup proofs; no paid Provider."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import urllib3
from app.config import get_settings
from app.delivery.models import Export
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.final_film import execute_final_film_node_run, queue_final_film_render
from app.production.final_film_uploads import cleanup_final_film_uploads
from app.runtime.scheduler import NodeRunScheduler
from app.storage import scratch
from app.storage.minio_store import MinioObjectStore
from minio import Minio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark

from fixtures.final_film_seed import _fake_enqueue, _seed_renderable_final_film


async def _queued(session, monkeypatch, store, *, key):
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, _, _ = await _seed_renderable_final_film(session, object_store=store)
    queued = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=edit.version,
        actor_id=user.id,
        idempotency_key=key,
        name="Fault proof",
    )
    await session.commit()
    return project.id, user.id, edit.id, queued.node_run_id


async def test_real_sigkill_preserves_journal_and_recovers_only_orphans(
    pg_session,
    monkeypatch,
    tmp_path,
):
    session = pg_session
    store = MinioObjectStore(get_settings())
    project_id, _, _, run_id = await _queued(session, monkeypatch, store, key="kill-proof")
    temp_root = tmp_path / "worker-temp"
    temp_root.mkdir()
    process = subprocess.Popen(
        [sys.executable, "tests/fixtures/final_film_kill_worker.py", str(run_id)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "TMPDIR": str(temp_root)},
    )
    assert process.stdout is not None
    try:
        line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 25)
        assert line, (
            process.stderr.read() if process.poll() is not None else "worker not at upload barrier"
        )
        evidence = json.loads(line)
        key, directory = evidence["uploaded_key"], Path(evidence["scratch"])
        assert await store.get_size(object_key=key) > 0
        assert directory.parent == temp_root / "dramaforge-owned-media-v1"
        monkeypatch.setattr(scratch, "_root", lambda: directory.parent)
        assert scratch.sweep_owned_media() == 0
        process.kill()
        await asyncio.to_thread(process.wait, 10)
        assert scratch.sweep_owned_media() == 1 and not directory.exists()
        operation = await session.scalar(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run_id)
        )
        assert (
            operation.request_summary["upload_objects"] and operation.status == "submission_started"
        )
        assert await cleanup_final_film_uploads(session, node_run_id=run_id, store=store) == 0
        operation.submitted_at = datetime.now(UTC) - timedelta(minutes=32)
        await session.commit()
        assert await cleanup_final_film_uploads(session, node_run_id=run_id, store=store) >= 1
        with pytest.raises(KeyError):
            await store.get_size(object_key=key)
        assert (
            await session.scalar(
                select(func.count()).select_from(Export).where(Export.project_id == project_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.produced_by_run_id == run_id)
            )
            == 0
        )
        # Unknown in-flight PUTs keep their journal even after a successful sweep.
        await session.refresh(operation)
        assert operation.request_summary["upload_objects"]
        assert operation.request_summary["uploads_finished"] is False
    finally:
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait, 10)
        for handle in (process.stdout, process.stderr):
            if handle:
                handle.close()


async def test_storage_response_loss_and_concurrent_cleanup_keep_successful_delivery(
    pg_session,
    monkeypatch,
):
    session = pg_session
    settings = get_settings()
    store = MinioObjectStore(settings)
    project_id, _, _, run_id = await _queued(session, monkeypatch, store, key="network-proof")
    run = await session.get(NodeRun, run_id)
    run.status = "running"
    await session.commit()
    node = await session.get(GraphNode, run.graph_node_id)
    target = urlsplit(settings.minio_endpoint)
    dropped = []

    async def lose_response(reader, writer):
        upstream_reader, upstream_writer = await asyncio.open_connection(
            target.hostname, target.port or 9000
        )
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = next(
                (
                    int(line.split(b":", 1)[1])
                    for line in header.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                ),
                0,
            )
            upstream_writer.write(header)
            while length:
                chunk = await reader.read(min(65536, length))
                if not chunk:
                    raise ConnectionError("incomplete request")
                upstream_writer.write(chunk)
                await upstream_writer.drain()
                length -= len(chunk)
            await upstream_writer.drain()
            # Actual MinIO has answered the completed write. Drop that response
            # before the SDK sees it, rather than replacing storage with a mock.
            await upstream_reader.readuntil(b"\r\n\r\n")
            dropped.append(True)
        finally:
            upstream_writer.close()
            writer.close()
            await upstream_writer.wait_closed()
            await writer.wait_closed()

    server = await asyncio.start_server(lose_response, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    class DisconnectedUploadStore(MinioObjectStore):
        def iter_bytes(self, **kwargs):
            return store.iter_bytes(**kwargs)

    disconnected = DisconnectedUploadStore(settings)
    disconnected._client = Minio(
        f"127.0.0.1:{port}",
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
        region=settings.minio_region,
        http_client=urllib3.PoolManager(retries=False, timeout=urllib3.Timeout(connect=2, read=2)),
    )
    try:
        with pytest.raises((OSError, urllib3.exceptions.HTTPError)):
            await execute_final_film_node_run(session, run=run, node=node, obj_store=disconnected)
        assert dropped, "the failure must happen after a real MinIO response"
    finally:
        server.close()
        await server.wait_closed()
    await session.refresh(run)
    assert run.status == "failed"
    operation = await session.scalar(
        select(ProviderOperation).where(ProviderOperation.node_run_id == run_id)
    )
    keys = list(operation.request_summary["upload_objects"])
    assert keys, "failed network cleanup must keep discoverable keys"
    assert (
        await session.scalar(
            select(func.count()).select_from(Export).where(Export.project_id == project_id)
        )
        == 0
    )

    # A separate successful film runs while two cleanup callers compete on the
    # failed upload. They must preserve its Artifact and every source object.
    good_project, _, _, good_id = await _queued(session, monkeypatch, store, key="successful-proof")
    good_run = await session.get(NodeRun, good_id)
    good_run.status = "running"
    await session.commit()
    good_node = await session.get(GraphNode, good_run.graph_node_id)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)

    async def clean():
        async with factory() as separate:
            return await cleanup_final_film_uploads(separate, node_run_id=run_id, store=store)

    result, _, _ = await asyncio.gather(
        execute_final_film_node_run(session, run=good_run, node=good_node, obj_store=store),
        clean(),
        clean(),
    )
    artifact = await session.get(Artifact, result.artifact_id)
    assert artifact and await store.get_size(object_key=artifact.object_key) == artifact.byte_size
    assert (
        await session.scalar(
            select(func.count()).select_from(Export).where(Export.project_id == good_project)
        )
        == 1
    )
    for key in keys:
        with pytest.raises(KeyError):
            await store.get_size(object_key=key)


async def test_two_process_scoped_export_requests_share_one_run_and_completed_artifact(
    pg_session, monkeypatch
):
    session = pg_session
    store = MinioObjectStore(get_settings())
    project, user, edit, _, _ = await _seed_renderable_final_film(session, object_store=store)
    project_id, actor_id, edit_id = project.id, user.id, edit.id
    enqueued = []

    async def enqueue(_self, node_run_id):
        enqueued.append(node_run_id)
        return f"job-{node_run_id}"

    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", enqueue)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)

    async def request():
        async with factory() as separate:
            result = await queue_final_film_render(
                separate,
                project_id=project_id,
                edit_session_id=edit_id,
                expected_timeline_version=1,
                actor_id=actor_id,
                idempotency_key="concurrent-export",
                name="Concurrent",
            )
            await separate.commit()
            return result

    first, second = await asyncio.gather(request(), request())
    assert first.node_run_id == second.node_run_id and len(enqueued) == 1
    run = await session.get(NodeRun, first.node_run_id)
    node = await session.get(GraphNode, run.graph_node_id)
    run.status = "running"
    await session.commit()
    completed = await execute_final_film_node_run(session, run=run, node=node, obj_store=store)
    replay_a, replay_b = await asyncio.gather(request(), request())
    assert replay_a.node_run_id == replay_b.node_run_id == run.id
    assert replay_a.result.artifact_id == replay_b.result.artifact_id == completed.artifact_id
    assert len(enqueued) == 1
    assert (
        await session.scalar(
            select(func.count()).select_from(Export).where(Export.project_id == project_id)
        )
        == 1
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(ProviderOperation)
            .where(ProviderOperation.node_run_id == run.id)
        )
        == 1
    )
    artifact = await session.get(Artifact, completed.artifact_id)
    assert await store.get_size(object_key=artifact.object_key) == artifact.byte_size
