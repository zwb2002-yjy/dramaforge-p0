"""Concurrent commands recheck a locked target before accepting its version."""

import asyncio

import pytest
from app.assets.models import Episode, Scene
from app.director.proposal_commands import ProposalCommandError, ProposalCommandRegistry
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark
from test_phase10_rls_modelres_audit_pg import _seed_user_workspace_projects


@pytest.mark.asyncio
@pytest.mark.parametrize("command,kind,field", [
    ("shot.update_image_prompt", "shot", "image_prompt"),
    ("story.upsert_episode", "episode", "title"),
    ("story.upsert_scene", "scene", "location_name"),
    ("story.upsert_shot", "shot", "visual_description"),
])
async def test_two_proposals_cannot_overwrite_the_same_version_pg(
    pg_session, command, kind, field,
):
    from uuid import uuid4

    seeded = await _seed_user_workspace_projects(pg_session, uuid4().hex[:8])
    project, shot, user = seeded["project_b"], seeded["shot"], seeded["user"]
    scene = await pg_session.get(Scene, shot.scene_id)
    episode = await pg_session.get(Episode, scene.episode_id)
    target = {"shot": shot, "scene": scene, "episode": episode}[kind]
    model, target_id, original_version = type(target), target.id, target.version
    project_id, user_id = project.id, user.id
    base = {"shot_id": str(shot.id), "episode_number": episode.episode_number,
            "scene_number": scene.scene_number, "shot_number": shot.shot_number}
    await pg_session.commit()
    factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
    written, release, second_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids, results = {}, {}

    async def apply(name):
        async with factory() as session:
            pids[name] = await session.scalar(text("SELECT pg_backend_pid()"))
            cached = await session.get(model, target_id)
            assert cached.version == original_version
            if name == "second":
                second_ready.set()
            try:
                await ProposalCommandRegistry(session, actor_id=user_id).apply(
                    project_id=project_id, command=command,
                    payload={**base, field: name}, expected_target_version=original_version,
                )
                results[name] = "accepted"
                if name == "first":
                    written.set()
                    await release.wait()
                await session.commit()
            except ProposalCommandError as exc:
                results[name] = exc.details.get("code")
                await session.rollback()

    first = asyncio.create_task(apply("first"))
    second = None
    try:
        await asyncio.wait_for(written.wait(), timeout=10)
        second = asyncio.create_task(apply("second"))
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
    assert results == {"first": "accepted", "second": "PROPOSAL_STALE"}
    pg_session.expire_all()
    final = await pg_session.scalar(select(model).where(model.id == target_id))
    assert final.version == original_version + 1
    assert getattr(final, field) == "first"
