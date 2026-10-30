"""Real PG/RLS proof for upload discovery and safe interrupted-film cleanup."""

from datetime import UTC, datetime, timedelta

import pytest
from app.execution.models import Artifact, ProviderOperation
from app.production.final_film_uploads import cleanup_final_film_uploads
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import func, select, text
from test_phase5_restart_recovery_pg import _project, _seed_graph_and_run
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark


@pytest.mark.parametrize("uploads_finished", [False, True])
async def test_scanner_and_cleanup_under_restricted_role_keep_referenced_objects(
    pg_session, uploads_finished
):
    session = pg_session
    user, project_id, _workspace = await _project(session)
    run = await _seed_graph_and_run(
        session,
        project_id=project_id,
        user_id=user.id,
        node_key="final_film_assembly",
        node_type="composite",
        status="running",
    )
    run_id = run.id
    prefix = f"projects/{project_id}/final-film/{run_id}/"
    store = InMemoryObjectStore()
    kept = await store.put_bytes(
        object_key=prefix + "kept.mp4", data=b"kept", mime_type="video/mp4"
    )
    orphan = await store.put_bytes(
        object_key=prefix + "orphan.srt", data=b"orphan", mime_type="text/plain"
    )
    session.add(
        Artifact(
            project_id=project_id,
            artifact_type="video",
            storage_state="available",
            object_key=kept.object_key,
            content_hash=kept.content_hash,
            byte_size=kept.byte_size,
            mime_type=kept.mime_type,
            produced_by_run_id=run_id,
        )
    )
    operation = ProviderOperation(
        node_run_id=run_id,
        attempt_no=1,
        purpose="primary",
        operation_kind="final_film.compose",
        actual_provider="local_ffmpeg",
        actual_model="ffmpeg-timeline-v2",
        request_fingerprint=run.input_hash,
        status="submission_started",
        submitted_at=datetime.now(UTC),
        request_summary={
            "upload_objects": [kept.object_key, orphan.object_key],
            "uploads_finished": uploads_finished,
        },
        response_summary={},
        execution_path_version="local-final-film-worker-v2",
    )
    session.add(operation)
    await session.commit()
    await session.execute(text("SET LOCAL ROLE dramaforge_app"))
    assert (
        run_id
        not in (
            await session.scalars(
                text("SELECT node_run_id FROM app.final_film_upload_contexts(1000)")
            )
        ).all()
    )
    await session.rollback()
    await session.refresh(operation)
    operation.submitted_at = datetime.now(UTC) - timedelta(minutes=32)
    await session.commit()
    await session.execute(text("SET LOCAL ROLE dramaforge_app"))
    assert (
        run_id
        in (
            await session.scalars(
                text("SELECT node_run_id FROM app.final_film_upload_contexts(50)")
            )
        ).all()
    )
    assert await cleanup_final_film_uploads(session, node_run_id=run_id, store=store) == 1
    assert await store.get_bytes(object_key=kept.object_key) == b"kept"
    assert store.keys() == [kept.object_key]
    assert operation.request_summary["upload_objects"] == (
        [] if uploads_finished else [kept.object_key, orphan.object_key]
    )
    await session.refresh(run)
    assert run.status == "failed"


async def test_unfinished_upload_cleanup_rotates_without_starving_later_operations(pg_session):
    session = pg_session
    user, project_id, _workspace = await _project(session)
    run_ids = []
    oldest = await session.scalar(select(func.min(ProviderOperation.updated_at)))
    first_scan_time = (oldest or datetime.now(UTC)) - timedelta(days=2)
    for index in range(2):
        run = await _seed_graph_and_run(
            session,
            project_id=project_id,
            user_id=user.id,
            node_key="final_film_assembly",
            node_type="composite",
            status="failed",
        )
        run_ids.append(run.id)
        session.add(
            ProviderOperation(
                node_run_id=run.id,
                attempt_no=1,
                purpose="primary",
                operation_kind="final_film.compose",
                actual_provider="local_ffmpeg",
                actual_model="ffmpeg-timeline-v2",
                request_fingerprint=run.input_hash,
                status="failed",
                request_summary={
                    "upload_objects": [f"projects/{project_id}/final-film/{run.id}/late.mp4"],
                    "uploads_finished": False,
                },
                response_summary={},
                updated_at=first_scan_time + timedelta(days=index),
            )
        )
    await session.commit()
    await session.execute(text("SET LOCAL ROLE dramaforge_app"))
    scanner = text("SELECT node_run_id FROM app.final_film_upload_contexts(1)")
    assert await session.scalar(scanner) == run_ids[0]
    await cleanup_final_film_uploads(session, node_run_id=run_ids[0], store=InMemoryObjectStore())
    await session.execute(text("SET LOCAL ROLE dramaforge_app"))
    assert await session.scalar(scanner) == run_ids[1]
