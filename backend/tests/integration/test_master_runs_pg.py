"""MasterRun RLS, append-only evidence, origin binding and refuse-loud downgrade."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.director.assistant_models import DirectorThread
from app.director.master_run_models import (
    DirectorMasterRun,
    DirectorMasterRunControlReceipt,
)
from app.director.master_runs import MasterRunService
from app.director.proposal_models import DirectorProposal
from app.director.turn_models import DirectorTurn
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError
from pg_support import alembic_head
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import (
    _alembic,
    _async_url,
    _create_database,
    _drop_database,
)
from test_director_turn_lifecycle_pg import pytestmark as pytestmark

BACKEND = Path(__file__).resolve().parents[2]


def migration(name, direction, target=None):
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, *([target] if target is not None else [])],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": _async_url(name)},
        capture_output=True,
        text=True,
        check=False,
    )


@asynccontextmanager
async def master_database():
    name = f"dramaforge_master_{uuid4().hex[:10]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        _alembic(name)
        yield name, engine, factory
    finally:
        await engine.dispose()
        await _drop_database(name)


async def _seed(session, *, kind: str = "agent"):
    owner = User(email=f"{uuid4()}@example.com", display_name="Owner", password_hash="x")
    other = User(email=f"{uuid4()}@example.com", display_name="Other", password_hash="x")
    session.add_all([owner, other])
    await session.flush()
    workspace = Workspace(name="机构", owner_user_id=owner.id)
    foreign_workspace = Workspace(name="其它", owner_user_id=other.id)
    session.add_all([workspace, foreign_workspace])
    await session.flush()
    project = Project(
        workspace_id=workspace.id, name="甲", aspect_ratio="16:9", budget_limit=0,
        work_type="serial_comic",
    )
    other_project = Project(
        workspace_id=foreign_workspace.id, name="乙", aspect_ratio="16:9", budget_limit=0,
        work_type="serial_comic",
    )
    session.add_all([project, other_project])
    await session.flush()
    thread = DirectorThread(
        project_id=project.id, scope_type="project", scope_entity_id=project.id,
        title="机构创作", created_by=owner.id,
    )
    session.add(thread)
    await session.flush()
    turn = DirectorTurn(
        workspace_id=workspace.id, project_id=project.id, actor_id=owner.id,
        thread_id=thread.id, turn_kind=kind, scope_type="project", scope_entity_id=project.id,
        request_key=f"turn-{uuid4().hex}", context_hash="a" * 64, status="thinking",
    )
    session.add(turn)
    await session.flush()
    proposal = DirectorProposal(
        project_id=project.id, thread_id=thread.id, scope_type="project",
        scope_entity_id=project.id, created_by=owner.id,
    )
    session.add(proposal)
    await session.flush()
    return (
        owner, other, workspace, foreign_workspace, project, other_project, thread, turn, proposal,
    )


def _plan(run, **overrides):
    data = {
        "goal": run.goal,
        "flows": [],
        "dependencies": [],
        "completion": [{"rule_id": "all_required_steps_succeeded"}],
        "input_versions": {},
        "limits": {"max_steps": 3},
        "decision_basis": {
            "expected_run_revision": run.revision,
            "expected_control_epoch": run.control_epoch,
            "current_plan_id": None,
            "current_plan_revision": None,
        },
    }
    data.update(overrides)
    return data


async def test_run_scope_append_only_evidence_and_real_cas_under_app_role():
    async with master_database() as (name, engine, factory):
        async with factory() as session:
            (
                owner, other, workspace, foreign_workspace, project, other_project,
                thread, turn, proposal,
            ) = await _seed(session)
            session.info["selected_workspace_id"] = workspace.id
            run = await MasterRunService(
                session, actor=owner, project=project,
            ).create_for_origin_turn(
                turn_id=turn.id, goal="整理古城灯会资料",
            )
            plan = await MasterRunService(
                session, actor=owner, project=project,
            ).append_plan(run_id=run.id, proposal_id=proposal.id, plan_data=_plan(run))
            await session.commit()
            ids = {
                "owner": owner.id, "workspace": workspace.id, "project": project.id,
                "run": run.id, "plan": plan.id, "turn": turn.id,
                "other": other.id, "foreign_workspace": foreign_workspace.id,
                "other_project": other_project.id,
            }
        async with factory() as session:
            # An ordinary foreign owner sees nothing, even with a valid workspace.
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["other"], workspace_id=ids["foreign_workspace"],
                project_id=ids["other_project"],
            )
            actor = await session.get(User, ids["other"])
            foreign_project = await session.get(Project, ids["other_project"])
            service = MasterRunService(session, actor=actor, project=foreign_project)
            with pytest.raises(NotFoundError):
                await service.get(ids["run"])
            assert await session.scalar(select(func.count(DirectorMasterRun.id))) == 0
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["owner"], workspace_id=ids["workspace"],
                project_id=ids["project"],
            )
            actor = await session.get(User, ids["owner"])
            project = await session.get(Project, ids["project"])
            service = MasterRunService(session, actor=actor, project=project)
            assert (await service.get(ids["run"])).id == ids["run"]
            # Control is allowed; the receipt is append-only evidence.
            receipt = await service.control(
                run_id=ids["run"], operation="pause", expected_revision=1,
            )
            assert receipt["result_revision"] == 2
            with pytest.raises(IntegrityError):
                # A second receipt for the same operation+revision is impossible.
                session.add(DirectorMasterRunControlReceipt(
                    project_id=ids["project"], master_run_id=ids["run"], actor_id=ids["owner"],
                    operation="pause", expected_revision=1, request_hash="b" * 64,
                    result_revision=2, result_data={},
                ))
                await session.flush()
            await session.rollback()
        async with factory() as session:
            await session.execute(text("SET LOCAL ROLE dramaforge_app"))
            await set_rls_context(
                session, user_id=ids["owner"], workspace_id=ids["workspace"],
                project_id=ids["project"],
            )
            for statement in (
                "UPDATE director_master_run_plans SET revision = 9",
                "DELETE FROM director_master_run_plans",
                "UPDATE director_master_run_control_receipts SET result_data = '{}'::jsonb",
                "DELETE FROM director_master_runs",
            ):
                with pytest.raises(ProgrammingError):
                    async with session.begin_nested():
                        await session.execute(text(statement))
            # The run row itself stays mutable for status/control fields.
            async with session.begin_nested():
                await session.execute(
                    text("UPDATE director_master_runs SET wait_reason = 'production_pending'")
                )


async def test_origin_binding_rejects_workflow_turns_and_keeps_terminal_invariants():
    async with master_database() as (name, engine, factory):
        async with factory() as session:
            (
                owner, other, workspace, foreign_workspace, project, other_project,
                thread, turn, proposal,
            ) = await _seed(session, kind="workflow")
            session.info["selected_workspace_id"] = workspace.id
            # A workflow turn can never own a continuous goal (composite FK/kind).
            # The origin constraint is deferred, so the refusal happens at commit.
            with pytest.raises(DBAPIError):
                session.add(DirectorMasterRun(
                    project_id=project.id, workspace_id=workspace.id, actor_id=owner.id,
                    source_thread_id=thread.id, origin_turn_id=turn.id,
                    origin_turn_kind="agent", goal="非法来源",
                ))
                await session.flush()
                await session.commit()
            await session.rollback()
        async with factory() as session:
            (
                owner, other, workspace, foreign_workspace, project, other_project,
                thread, turn, proposal,
            ) = await _seed(session)
            session.info["selected_workspace_id"] = workspace.id
            run = await MasterRunService(
                session, actor=owner, project=project,
            ).create_for_origin_turn(
                turn_id=turn.id, goal="整理古城灯会资料",
            )
            await session.commit()
            run_id = run.id
        async with factory() as session:
            run = await session.get(DirectorMasterRun, run_id)
            # Terminal status and finished_at are equivalent by construction.
            for invalid in (
                "status='succeeded'",
                "status='cancelled',finished_at=now() - interval '1 day'",
                "archived_at=now()",
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(text(
                            f"UPDATE director_master_runs SET {invalid} WHERE id=:id"
                        ), {"id": run_id})
            async with session.begin_nested():
                await session.execute(text(
                    "UPDATE director_master_runs SET status='cancelled', finished_at=now() "
                    "WHERE id=:id"
                ), {"id": run_id})
            async with session.begin_nested():
                await session.execute(text(
                    "UPDATE director_master_runs SET archived_at=now() WHERE id=:id"
                ), {"id": run_id})
            assert run.id == run_id


async def test_populated_master_run_history_blocks_downgrade():
    name = f"dramaforge_master_mig_{uuid4().hex[:8]}"
    await _create_database(name)
    engine = create_async_engine(_async_url(name))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        assert migration(name, "upgrade", "head").returncode == 0
        async with factory() as session:
            (
                owner, other, workspace, foreign_workspace, project, other_project,
                thread, turn, proposal,
            ) = await _seed(session)
            session.info["selected_workspace_id"] = workspace.id
            await MasterRunService(session, actor=owner, project=project).create_for_origin_turn(
                turn_id=turn.id, goal="整理古城灯会资料",
            )
            await session.commit()
        refused = migration(name, "downgrade", "20261117_0101")
        assert refused.returncode != 0
        assert "MASTER_RUNS_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE" in refused.stderr
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == alembic_head()
        checked = migration(name, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
    finally:
        await engine.dispose()
        await _drop_database(name)
