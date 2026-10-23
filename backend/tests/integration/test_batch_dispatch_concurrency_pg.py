"""PostgreSQL proof: batch paid-dispatch serialization (backend-review N-05/S3).

Runs the real migration chain and the real advisory-lock path. Two concurrent
dispatches of the same confirmed preview -- with different batch keys -- may
create the authorized runs exactly once; the loser is rejected, never billed
twice. This test never performs a Provider call.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.execution.models import NodeRun
from app.production.application import batch_production as batch
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError
from app.shared.security import hash_password
from model_infra_fixture import seed_model_infra
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def _seed(factory) -> tuple[object, object, object, object]:
    """Register an owner, workspace, project and one image shot; return ids."""

    async with factory() as session:
        user = User(
            email=f"pgbatch-{uuid4().hex}@example.com",
            display_name="PG Batch",
            password_hash=hash_password("x"),
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
        session.add(workspace)
        await session.flush()
        project = Project(
            workspace_id=workspace.id,
            name="Batch Concurrency",
            aspect_ratio="9:16",
            budget_limit=0,
        )
        session.add(project)
        await session.flush()
        await seed_model_infra(session, project=project, user=user)
        episode = Episode(
            project_id=project.id, episode_number=1, title="E1", synopsis=""
        )
        session.add(episode)
        await session.flush()
        scene = Scene(
            episode_id=episode.id,
            scene_number=1,
            location_name="Studio",
            time_of_day="day",
            synopsis="",
        )
        session.add(scene)
        await session.flush()
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=1,
            version=1,
            visual_description="A pg batch image shot",
            image_prompt="character walks into frame",
        )
        session.add(shot)
        await session.commit()
        return project.id, workspace.id, user.id, shot.id


async def _dispatch(factory, *, project_id, workspace_id, actor_id, body):
    """Run one authenticated dispatch inside its own session and RLS scope."""

    async with factory() as session:
        await session.execute(text("SET LOCAL ROLE dramaforge_app"))
        await set_rls_context(
            session, user_id=actor_id, workspace_id=workspace_id, project_id=project_id
        )
        actor = await session.get(User, actor_id)
        assert actor is not None
        result = await batch.dispatch_batch_production(
            project_id,
            batch.BatchProductionDispatchBody(**body),
            actor,
            session,
        )
        await session.commit()
        return result


@pytest.mark.asyncio
async def test_concurrent_dispatch_same_preview_authorizes_once():
    """Two concurrent dispatches of one confirmed preview authorize once."""

    dbname = f"dramaforge_pb_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, workspace_id, actor_id, shot_id = await _seed(factory)

        # Freeze the exact confirmed preview once, through the real service.
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session,
                user_id=actor_id,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            project = await session.get(Project, project_id)
            assert project is not None
            preview, prepared = await batch._prepare(
                session,
                project=project,
                user_id=actor_id,
                stage="image_keyframe",
                scene_id=None,
            )
            await session.commit()
            assert preview.ready_count == 1
            assert shot_id in prepared

        body = {
            "stage": "image_keyframe",
            "scene_id": None,
            "preview_fingerprint": preview.fingerprint,
            "batch_key": "concurrent-first",
            "max_provider_calls": 1,
            "owner_authorized": True,
        }
        other_body = {**body, "batch_key": "concurrent-second"}

        results = await asyncio.gather(
            _dispatch(
                factory,
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=actor_id,
                body=body,
            ),
            _dispatch(
                factory,
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=actor_id,
                body=other_body,
            ),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, BaseException)]
        conflicts = [r for r in results if isinstance(r, ConflictError)]
        assert len(successes) == 1, [repr(r) for r in results]
        assert len(conflicts) == 1, [repr(r) for r in results]
        assert conflicts[0].details["code"] == "BATCH_PREVIEW_ALREADY_AUTHORIZED"

        # Exactly one batch media run exists for this project; the pure
        # upstream runs the pipeline requires are queued but un-billed.
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(NodeRun).where(NodeRun.project_id == project_id)
                    )
                ).all()
            )
        batch_runs = [
            row
            for row in rows
            if "batch:" in (row.idempotency_key or "")
        ]
        assert len(batch_runs) == 1
        assert batch_runs[0].status == "queued"
        authorization = (batch_runs[0].input_snapshot or {}).get("paid_authorization")
        assert authorization is not None
        assert authorization["authorized_call_count"] == 1
        assert authorization["preview_fingerprint"] == preview.fingerprint
    finally:
        await engine.dispose()
        await _drop_database(dbname)


@pytest.mark.asyncio
async def test_sequential_replay_same_key_returns_frozen_receipts():
    """A same-key replay returns the frozen receipts without new runs."""

    dbname = f"dramaforge_pb_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        project_id, workspace_id, actor_id, _shot_id = await _seed(factory)

        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session,
                user_id=actor_id,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            project = await session.get(Project, project_id)
            assert project is not None
            preview, _prepared = await batch._prepare(
                session,
                project=project,
                user_id=actor_id,
                stage="image_keyframe",
                scene_id=None,
            )
            await session.commit()

        body = {
            "stage": "image_keyframe",
            "scene_id": None,
            "preview_fingerprint": preview.fingerprint,
            "batch_key": "replay-key",
            "max_provider_calls": 1,
            "owner_authorized": True,
        }
        first = await _dispatch(
            factory,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            body=body,
        )
        # Capture the frozen authorization timestamp before the replay.
        async def _read_authorization() -> dict | None:
            async with factory() as session:
                rows = list(
                    (
                        await session.scalars(
                            select(NodeRun).where(NodeRun.project_id == project_id)
                        )
                    ).all()
                )
                batch_rows = [
                    row
                    for row in rows
                    if "batch:" in (row.idempotency_key or "")
                ]
                assert len(batch_rows) == 1
                return (batch_rows[0].input_snapshot or {}).get("paid_authorization")

        frozen_authorization = await _read_authorization()
        assert frozen_authorization is not None
        assert frozen_authorization["authorized_at"]

        replay = await _dispatch(
            factory,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            body=body,
        )
        assert first.node_run_ids == replay.node_run_ids
        assert first.accepted_count == replay.accepted_count == 1

        replayed_authorization = await _read_authorization()
        # The replay returned the frozen receipt and did not overwrite the
        # authorization facts (AGENTS.md: reuse facts frozen at creation).
        assert replayed_authorization == frozen_authorization
    finally:
        await engine.dispose()
        await _drop_database(dbname)
