"""Same-key local creations converge after real PG uniqueness/lock contention."""

import asyncio
from uuid import uuid4

import pytest
from app.access.models import User
from app.assets.from_artifact_service import AssetFromArtifactRequest, AssetFromArtifactService
from app.production.experiment_service import ExperimentCreateBody, create_experiment_branch
from app.production.review_gate import record_human_decision
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark
from tests.unit.test_review_gate import _artifact, _env, _review_run


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["asset", "experiment", "review"])
async def test_same_key_creations_converge_pg(pg_session, kind):
    user, project, shot = await _env(pg_session)
    artifact = await _artifact(pg_session, project_id=project.id)
    evidence = await _artifact(pg_session, project_id=project.id, hash_seed="b")
    run = await _review_run(pg_session, project_id=project.id, shot_id=shot.id,
        created_by=user.id, upstream_artifact_id=artifact.id, review_artifact_id=evidence.id)
    project_id, user_id, shot_id = project.id, user.id, shot.id
    artifact_id, run_id, version = artifact.id, run.id, shot.version
    key = f"same-key-{uuid4()}"
    await pg_session.commit()
    factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
    written, release, second_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids, results = {}, {}

    async def create(name):
        async with factory() as session:
            pids[name] = await session.scalar(text("SELECT pg_backend_pid()"))
            actor = await session.get(User, user_id)
            if name == "second":
                second_ready.set()
            if kind == "asset":
                row = await AssetFromArtifactService(session).create(
                    project_id=project_id, actor=actor, request_key=key,
                    request=AssetFromArtifactRequest(kind="character", name="Lead",
                        artifact_id=artifact_id, reference_role="front_face"),
                )
            elif kind == "experiment":
                row = await create_experiment_branch(session, project_id=project_id,
                    actor_id=user_id, body=ExperimentCreateBody(name="Experiment",
                        source_shot_id=shot_id, idempotency_key=key))
            else:
                row = await record_human_decision(session, project_id=project_id, shot_id=shot_id,
                    artifact_id=artifact_id, review_node_run_id=run_id, review_kind="identity",
                    decision="approved", reason="Owner reviewed", actor_id=user_id,
                    shot_version=version, request_key=key)
            results[name] = row.id
            if name == "first":
                written.set()
                await release.wait()
            await session.commit()

    first = asyncio.create_task(create("first"))
    second = None
    try:
        try:
            await asyncio.wait_for(written.wait(), timeout=10)
        except TimeoutError:
            if first.done():
                await first
            raise
        second = asyncio.create_task(create("second"))
        await asyncio.wait_for(second_ready.wait(), timeout=10)

        async def wait_for_lock():
            while True:
                blockers = await pg_session.scalar(text("SELECT pg_blocking_pids(:pid)"),
                                                   {"pid": pids["second"]})
                if pids["first"] in blockers:
                    return
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_lock(), timeout=10)
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
    assert results["first"] == results["second"]
