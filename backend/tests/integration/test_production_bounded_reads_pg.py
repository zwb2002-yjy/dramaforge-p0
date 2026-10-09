"""PostgreSQL proof for production projections, tied keysets and RLS isolation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.execution.models import Artifact
from app.execution.shot_pipeline import SHOT_NODES
from app.production.read_service import ProductionReadService
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_production_bounded_reads import add_run
from tests.unit.test_scene_workspace_snapshot import _seed


@pytest.mark.asyncio
async def test_bounded_production_reads_on_postgresql():
    dbname = f"dramaforge_bounded_reads_{uuid4().hex[:8]}"
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    try:
        _alembic(dbname)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            user, project, _, _, shot = await _seed(session)
            env = engine, session, user, project, shot
            rows = [await add_run(env, "failed", 1), await add_run(env, "completed", 2)]
            rows += [
                await add_run(env, "running", 3, execution_branch="experiment", experiment_id="e1")
            ]
            rows += [
                await add_run(env, "failed", 4, execution_branch="experiment", experiment_id="e2")
            ]
            timestamp = datetime(2026, 9, 1, 12, 0, 0, 123456, tzinfo=UTC)
            for row in rows:
                row.created_at = timestamp
            foreign, foreign_project, _, _, foreign_shot = await _seed(session)
            foreign_run = await add_run(
                (engine, session, foreign, foreign_project, foreign_shot), "completed"
            )
            for index in range(4):
                session.add(
                    Artifact(
                        project_id=project.id,
                        artifact_type="image",
                        object_key=f"bounded/{index}",
                        content_hash=uuid4().hex * 2,
                        byte_size=1,
                        mime_type="image/png",
                        storage_state="available",
                        created_at=timestamp,
                    )
                )
            await session.commit()
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=user.id, workspace_id=project.workspace_id, project_id=project.id
            )
            service = ProductionReadService(session)
            summary = await service.summary(project_id=project.id)
            assert (
                summary.total_runs,
                summary.completed_runs,
                summary.running_runs,
                summary.failed_runs,
            ) == (3, 1, 1, 1)
            assert [row.id for row in summary.recent_failures] == [rows[-1].id]
            assert [stage.node_key for stage in summary.stages] == list(SHOT_NODES)
            stages = {stage.node_key: stage for stage in summary.stages}
            assert stages["keyframe"].status_counts == {"completed": 1}
            assert stages["keyframe"].latest_failure is None
            assert all(
                not stage.status_counts for stage in summary.stages if stage.node_key != "keyframe"
            )
            foreign_summary = await service.summary(project_id=foreign_project.id)
            assert all(not stage.status_counts for stage in foreign_summary.stages)
            assert all(stage.latest_failure is None for stage in foreign_summary.stages)
            assert (await service.summary(project_id=foreign_project.id)).total_runs == 0
            assert (await service.runs(project_id=foreign_project.id)).items == []
            assert (await service.artifacts(project_id=foreign_project.id)).items == []
            with pytest.raises(NotFoundError):
                await service.statuses(project_id=project.id, run_ids=[rows[0].id, foreign_run.id])
            identities = [rows[2].id, rows[0].id]
            assert [
                row.id for row in await service.statuses(project_id=project.id, run_ids=identities)
            ] == identities
            first = await service.runs(project_id=project.id, limit=2)
            assert first.next_cursor is not None
            await session.execute(text("RESET ROLE"))
            new_run = await add_run(env, "queued", 5)
            new_run.created_at = timestamp + timedelta(seconds=1)
            await session.flush()
            second = await service.runs(project_id=project.id, limit=2, cursor=first.next_cursor)
            assert second.next_cursor is None
            ids = [row.id for page in [first, second] for row in page.items]
            assert ids == sorted([row.id for row in rows], reverse=True)
            expected_artifacts = set(
                (
                    await session.scalars(
                        select(Artifact.id).where(Artifact.project_id == project.id)
                    )
                ).all()
            )
            seen = []
            cursor = None
            for _ in range(10):
                page = await service.artifacts(project_id=project.id, limit=2, cursor=cursor)
                seen.extend(row.id for row in page.items)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
            else:
                pytest.fail("artifact keyset did not terminate")
            assert len(seen) == len(set(seen))
            assert set(seen) == expected_artifacts
    finally:
        await engine.dispose()
        await _drop_database(dbname)
