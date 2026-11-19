"""Domain BusinessFlow end-to-end through the worker's own sessions (I6b)."""

from __future__ import annotations

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
from test_master_runs import _decision, _seed, _turn


@pytest.mark.asyncio
async def test_domain_flow_completes_through_the_worker() -> None:
    import tempfile
    from pathlib import Path

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
            flows = _specs(
                project,
                [
                    _flow(
                        flow_key="project_asset_audit",
                        definition_key="project_asset_audit",
                        input_data={"limit": 5, "asset_id": str(asset.id)},
                    )
                ],
            )
            service = MasterRunService(
                session, actor=user, project=project, flow_registry=DEFAULT_DEFINITIONS
            )
            turn = await _turn(session, project, user, thread)
            run = await service.create_for_origin_turn(turn_id=turn.id, goal="audit")
            item = await _decision(session, project, user, thread)
            plan = await service.append_plan(
                run_id=run.id,
                decision_ref=item.id,
                plan_data=_plan(run, flows=flows),
                created_by_turn_id=turn.id,
            )
            await session.refresh(run)
            await service.apply_plan(
                run_id=run.id,
                plan_id=plan.id,
                expected_revision=run.revision,
                expected_control_epoch=run.control_epoch,
            )
            await session.commit()
            instance = await session.scalar(select(DirectorBusinessFlowInstance))
            assert instance is not None
            instance_id = instance.id

        result: dict[str, object] = {}
        for _ in range(6):
            result = await execute_business_flow(
                factory, instance_id=instance_id, registry=DEFAULT_DEFINITIONS
            )
            if result.get("status") in {"succeeded", "failed", "cancelled"}:
                break
        assert result.get("status") == "succeeded", result
        async with factory() as session:
            steps = (
                await session.execute(select(DirectorBusinessFlowStep))
            ).scalars().all()
            assert {step.step_key for step in steps} == {"list_assets", "read_asset"}
            assert all(step.status == "succeeded" for step in steps)
    finally:
        await engine.dispose()
