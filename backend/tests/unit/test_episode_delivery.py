"""Per-episode delivery is planned and started per episode, never project-wide (I9-02)."""

from __future__ import annotations

import pytest
from app.assets.models import Episode
from app.delivery.episode_delivery import EpisodeDeliveryService
from app.delivery.models import Export
from app.editing.timeline_builder import build_edit_session_for_project
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.test_edit_session_render import _exported_session


async def _episode_scoped_sessions(session: AsyncSession, project_id, user_id):
    """Give every episode its own scoped session built from production truth."""
    episodes = list(
        (
            await session.scalars(
                select(Episode)
                .where(Episode.project_id == project_id)
                .order_by(Episode.episode_number)
            )
        ).all()
    )
    built = []
    for episode in episodes:
        result = await build_edit_session_for_project(
            session, project_id=project_id, user_id=user_id, episode_id=episode.id
        )
        built.append((episode, result["session_id"]))
    await session.flush()
    return built


@pytest.mark.asyncio
async def test_episode_without_a_session_is_blocked_not_shipped(
    session: AsyncSession,
) -> None:
    project, user, _shot_row, _artifact, saved, _export, _store = await _exported_session(session)
    # The only session is project-wide (episode_id NULL), so nothing is deliverable.
    plan = await EpisodeDeliveryService(session).plan(project_id=project.id)
    assert len(plan) == 1
    assert plan[0].status == "blocked"
    assert plan[0].blockers == ("DELIVERY_SESSION_MISSING",)
    assert plan[0].export_id is None
    assert saved.episode_id is None


@pytest.mark.asyncio
async def test_start_freezes_one_export_and_render_per_episode(
    session: AsyncSession,
) -> None:
    project, user, _shot_row, _artifact, _saved, _export, _store = await _exported_session(session)
    # A second episode so the batch has two targets.
    second = Episode(project_id=project.id, episode_number=2, title="E2", synopsis="")
    session.add(second)
    await session.flush()
    first = await session.scalar(
        select(Episode).where(Episode.project_id == project.id, Episode.episode_number == 1)
    )
    assert first is not None
    # Give episode 1 a scoped session; episode 2 stays without one.
    built = await build_edit_session_for_project(
        session, project_id=project.id, user_id=user.id, episode_id=first.id
    )
    await session.commit()
    assert built["clips"]

    started = await EpisodeDeliveryService(session).start(
        project=project, actor_id=user.id, format="mp4"
    )
    await session.commit()

    by_episode = {item.episode_number: item for item in started}
    assert by_episode[1].status == "started"
    assert by_episode[1].export_id is not None and by_episode[1].node_run_id is not None
    assert by_episode[2].status == "blocked"
    assert by_episode[2].blockers == ("DELIVERY_SESSION_MISSING",)

    export = await session.get(Export, by_episode[1].export_id)
    assert export is not None
    assert export.episode_id == first.id
    assert export.format == "mp4"
    assert export.render_node_run_id == by_episode[1].node_run_id
    assert export.result_artifact_id is None  # queued, not delivered

    # Replaying the batch returns the same receipt instead of a second one.
    again = await EpisodeDeliveryService(session).start(
        project=project, actor_id=user.id, format="mp4"
    )
    await session.commit()
    assert {i.episode_number: i.export_id for i in again}[1] == export.id
    exports = list(await session.scalars(select(Export).where(Export.project_id == project.id)))
    # Only the batch's own episode receipt exists; the project-wide one from the
    # fixture stays untouched and is not counted here.
    assert [row.id for row in exports if row.episode_id == first.id] == [export.id]


@pytest.mark.asyncio
async def test_plan_reports_every_episode_in_order(session: AsyncSession) -> None:
    project, user, _shot_row, _artifact, _saved, _export, _store = await _exported_session(session)
    for number in (2, 3):
        session.add(
            Episode(project_id=project.id, episode_number=number, title=f"E{number}", synopsis="")
        )
    await session.flush()
    await _episode_scoped_sessions(session, project.id, user.id)
    await session.commit()
    plan = await EpisodeDeliveryService(session).plan(project_id=project.id)
    assert [item.episode_number for item in plan] == [1, 2, 3]
    assert {item.status for item in plan} == {"planned"}
    assert all(item.session_version == 1 for item in plan)
