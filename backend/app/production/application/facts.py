"""Production-owned queries expose committed facts without leaking ORM rows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.production_facts import ExecutionFact, ExecutionTrackingFact
from app.execution.models import NodeRun
from app.production.models import GraphVersion, ProductionGraph
from app.shared.errors import ValidationAppError


class ProductionFacts:
    def __init__(self, session: AsyncSession) -> None:
        # Callers establish authenticated workspace scope before constructing
        # this reader. Explicit project/shot predicates supplement database RLS.
        self._session = session

    async def tracking(self, *, project_id: UUID, run_id: UUID) -> ExecutionTrackingFact:
        result = await self._session.execute(
            select(NodeRun, ProductionGraph.scope_entity_id)
            .join(GraphVersion, GraphVersion.id == NodeRun.graph_version_id)
            .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
            .where(NodeRun.id == run_id, NodeRun.project_id == project_id,
                   ProductionGraph.project_id == project_id, ProductionGraph.scope_type == "shot")
            .execution_options(populate_existing=True)
        )
        row = result.one_or_none()
        if row is None:
            raise ValidationAppError("Execution tracking fact not found")
        run, shot_id = row
        snapshot = run.input_snapshot or {}
        plan = snapshot.get("workbench_plan")
        if not isinstance(plan, dict) or snapshot.get("shot_id") != str(shot_id):
            raise ValidationAppError("Execution tracking fact has no valid frozen plan")
        return ExecutionTrackingFact.model_validate({
            "id": run.id, "project_id": project_id, "shot_id": shot_id,
            "status": run.status, "stage": snapshot.get("stage", ""),
            "result_artifact_id": run.result_artifact_id, "input_hash": run.input_hash,
            "command_key": run.idempotency_key, "shot_version": plan.get("expected_shot_version"),
            "model_resolution": snapshot.get("execution_model_resolution") or {},
        })

    async def executions(
        self, *, project_id: UUID, shot_id: UUID, run_ids: tuple[UUID, ...],
    ) -> tuple[ExecutionFact, ...]:
        if not run_ids:
            raise ValidationAppError(
                "Execution fact lookup requires a run link",
                details={"code": "PRODUCTION_EXECUTION_LINK_MISSING"},
            )
        rows = (
            await self._session.execute(
                select(NodeRun)
                .join(GraphVersion, GraphVersion.id == NodeRun.graph_version_id)
                .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
                .where(
                    NodeRun.id.in_(run_ids),
                    NodeRun.project_id == project_id,
                    ProductionGraph.project_id == project_id,
                    ProductionGraph.scope_type == "shot",
                    ProductionGraph.scope_entity_id == shot_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
        facts = {
            row.id: ExecutionFact(
                id=row.id, project_id=project_id, shot_id=shot_id,
                status=row.status, stage=str((row.input_snapshot or {}).get("stage", "")),
                result_artifact_id=row.result_artifact_id,
            )
            for row in rows
        }
        if set(facts) != set(run_ids):
            raise ValidationAppError(
                "Execution link is missing or outside the requested scope",
                details={"code": "PRODUCTION_EXECUTION_LINK_MISSING"},
            )
        return tuple(facts[run_id] for run_id in run_ids)
