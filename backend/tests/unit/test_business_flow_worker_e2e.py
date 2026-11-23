"""Domain BusinessFlow end-to-end through the worker's own sessions (I6b)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
from app.assets.models import Asset
from app.director.business_flow_models import (
    DirectorBusinessFlowInstance,
    DirectorBusinessFlowStep,
)
from app.director.business_flow_worker import execute_business_flow
from app.director.business_flows import DEFAULT_DEFINITIONS
from app.director.master_runs import MasterRunService
from app.shared.base import Base
from app.shared.model_registry import load_all_models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_business_flows import _flow, _plan, _specs
from test_master_runs import _plan_proposal, _seed, _turn


async def _run_project_asset_audit(
    *, asset_id: str | None
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    load_all_models()
    tmp_dir = tempfile.mkdtemp(prefix="flow-e2e-")
    db_path = Path(tmp_dir) / "flow.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            project, user, thread = await _seed(session)
            session.info["selected_workspace_id"] = project.workspace_id
            asset = Asset(project_id=project.id, kind="character", name="Hero", version=1)
            session.add(asset)
            await session.flush()
            input_data: dict[str, object] = {"limit": 5}
            input_data["asset_id"] = asset_id or str(asset.id)
            flows = _specs(
                project,
                [
                    _flow(
                        flow_key="project_asset_audit",
                        definition_key="project_asset_audit",
                        input_data=input_data,
                    )
                ],
            )
            service = MasterRunService(
                session, actor=user, project=project, flow_registry=DEFAULT_DEFINITIONS
            )
            turn = await _turn(session, project, user, thread)
            run = await service.create_for_origin_turn(turn_id=turn.id, goal="audit")
            proposal = await _plan_proposal(session, project, user, thread)
            plan = await service.append_plan(
                run_id=run.id,
                proposal_id=proposal.id,
                plan_data=_plan(run, flows=flows),
                created_by_turn_id=turn.id,
            )
            await session.refresh(run)
            await service.apply_plan(
                decision_ref=plan.decision_ref, expected_plan_hash=plan.plan_hash,
                run_id=run.id,
                plan_id=plan.id,
                expected_revision=run.revision,
                expected_control_epoch=run.control_epoch,
            )
            await session.commit()
            instance = await session.scalar(select(DirectorBusinessFlowInstance))
            assert instance is not None
            instance_id = instance.id

        result: dict[str, Any] = {}
        for _ in range(6):
            result = await execute_business_flow(
                factory, instance_id=instance_id, registry=DEFAULT_DEFINITIONS
            )
            if result.get("status") in {"succeeded", "failed", "cancelled"}:
                break
        async with factory() as session:
            steps = (
                await session.execute(select(DirectorBusinessFlowStep))
            ).scalars().all()
            snapshot = [(step.step_key, step.status) for step in steps]
        return result, snapshot
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_domain_flow_completes_through_the_worker() -> None:
    result, steps = await _run_project_asset_audit(asset_id=None)
    assert result.get("status") == "succeeded", result
    assert dict(steps) == {"list_assets": "succeeded", "read_asset": "succeeded"}


@pytest.mark.asyncio
async def test_domain_flow_keeps_partial_success_when_a_step_fails() -> None:
    result, steps = await _run_project_asset_audit(
        asset_id="00000000-0000-4000-8000-000000000000"
    )
    assert result.get("status") == "failed", result
    assert dict(steps) == {"list_assets": "succeeded", "read_asset": "failed"}


@pytest.mark.asyncio
async def test_domain_flow_replans_after_a_failed_instance() -> None:
    load_all_models()
    tmp_dir = tempfile.mkdtemp(prefix="flow-replan-")
    db_path = Path(tmp_dir) / "flow.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            project, user, thread = await _seed(session)
            session.info["selected_workspace_id"] = project.workspace_id
            asset = Asset(project_id=project.id, kind="character", name="Hero", version=1)
            session.add(asset)
            await session.flush()
            bad_input = {"limit": 5, "asset_id": "00000000-0000-4000-8000-000000000000"}
            good_input = {"limit": 5, "asset_id": str(asset.id)}
            flows = _specs(
                project,
                [
                    _flow(
                        flow_key="project_asset_audit",
                        definition_key="project_asset_audit",
                        input_data=bad_input,
                    )
                ],
            )
            service = MasterRunService(
                session, actor=user, project=project, flow_registry=DEFAULT_DEFINITIONS
            )
            turn = await _turn(session, project, user, thread)
            run = await service.create_for_origin_turn(turn_id=turn.id, goal="audit")
            proposal = await _plan_proposal(session, project, user, thread)
            first_plan = await service.append_plan(
                run_id=run.id,
                proposal_id=proposal.id,
                plan_data=_plan(run, flows=flows),
                created_by_turn_id=turn.id,
            )
            await session.refresh(run)
            await service.apply_plan(
                decision_ref=first_plan.decision_ref, expected_plan_hash=first_plan.plan_hash,
                run_id=run.id,
                plan_id=first_plan.id,
                expected_revision=run.revision,
                expected_control_epoch=run.control_epoch,
            )
            await session.commit()
            failed_instance = await session.scalar(select(DirectorBusinessFlowInstance))
            assert failed_instance is not None
            failed_id = failed_instance.id

        for _ in range(6):
            result = await execute_business_flow(
                factory, instance_id=failed_id, registry=DEFAULT_DEFINITIONS
            )
            if result.get("status") in {"succeeded", "failed", "cancelled"}:
                break
        assert result.get("status") == "failed", result

        async with factory() as session:
            project = await session.get(type(project), project.id)
            user = await session.get(type(user), user.id)
            run = await session.get(type(run), run.id)
            proposal = await _plan_proposal(session, project, user, thread)
            service = MasterRunService(
                session, actor=user, project=project, flow_registry=DEFAULT_DEFINITIONS
            )
            replanned = await service.append_plan(
                run_id=run.id,
                proposal_id=proposal.id,
                plan_data=_plan(
                    run,
                    flows=_specs(
                        project,
                        [
                            _flow(
                                flow_key="project_asset_audit",
                                definition_key="project_asset_audit",
                                input_data=good_input,
                            )
                        ],
                    ),
                    current_plan=await service.current_plan(run),
                ),
                created_by_turn_id=turn.id,
            )
            await session.refresh(run)
            await service.apply_plan(
                decision_ref=replanned.decision_ref, expected_plan_hash=replanned.plan_hash,
                run_id=run.id,
                plan_id=replanned.id,
                expected_revision=run.revision,
                expected_control_epoch=run.control_epoch,
            )
            await session.commit()
            instances = (
                await session.execute(select(DirectorBusinessFlowInstance))
            ).scalars().all()
            new_instance = next(item for item in instances if item.id != failed_id)
            new_id = new_instance.id

        for _ in range(6):
            result = await execute_business_flow(
                factory, instance_id=new_id, registry=DEFAULT_DEFINITIONS
            )
            if result.get("status") in {"succeeded", "failed", "cancelled"}:
                break
        assert result.get("status") == "succeeded", result
    finally:
        await engine.dispose()
