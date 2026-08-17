"""Materialize one creator-selected, separately authorized local repair."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.director.enums import ApprovalKind, ArtifactKind, WorkflowStatus
from app.director.models import (
    BudgetReservation,
    CreativeArtifactVersion,
    ProductionBatch,
    ProductionBatchShot,
    WorkflowStepRun,
)
from app.director.production_service import DirectorProductionService
from app.director.production_templates import (
    DIALOGUE_POST_DUB_SHOT_V1,
    QUALITY_POLICY_V1,
)
from app.director.service import DirectorService, content_hash
from app.director.shooting import (
    CharacterBiblePayload,
    RepairOptionPayload,
    RepairPlanPayload,
    SelectionPlanPayload,
    StoryboardPlanPayload,
    VisualBiblePayload,
    VoiceBiblePayload,
)
from app.events.service import EventService
from app.execution.models import GraphNode, NodeRun
from app.shared.db import set_rls_context
from app.shared.errors import ConflictError, ValidationAppError

_SUCCESS = frozenset({"completed", "cached", "completed_after_cancel"})


class DirectorRepairExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._director = DirectorService(session)
        self._projects = ProjectService(session)
        self._production = DirectorProductionService(session)
        self._events = EventService(session)

    async def authorize_and_materialize(
        self,
        *,
        project_id: UUID,
        repair_option_id: str,
        budget_authorization_id: UUID,
        actor: User,
        idempotency_key: str,
    ) -> tuple[ProductionBatch, list[NodeRun]]:
        project = await self._projects.get_project_for_owner(
            project_id=project_id, actor=actor
        )
        workflow = await self._director.get_workflow(
            project_id=project_id, actor=actor, for_update=True
        )
        existing = await self._production._batch_by_key(project_id, idempotency_key)
        if existing is not None:
            if existing.batch_kind != "repair":
                raise ConflictError("idempotency key belongs to another batch kind")
            return existing, await self._production._batch_runs(existing.id)
        if workflow.status == WorkflowStatus.AWAITING_REPAIR_AUTHORIZATION.value:
            await self._director.approve(
                project_id=project_id,
                actor=actor,
                approval_kind=ApprovalKind.REPAIR_BUDGET,
                idempotency_key=f"{idempotency_key}:approval",
                reason=f"selected repair option {repair_option_id}",
                budget_authorization_id=budget_authorization_id,
            )
            # DirectorService.approve commits the approval. PostgreSQL SET LOCAL
            # values are transaction-scoped, so restore the exact project scope
            # before any follow-up query in this request.
            await set_rls_context(
                self._session,
                user_id=actor.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
            workflow = await self._director.get_workflow(
                project_id=project_id, actor=actor, for_update=True
            )
        if workflow.status != WorkflowStatus.PRODUCTION_RUNNING.value:
            raise ValidationAppError(
                "repair requires an explicit active budget approval",
                details={"code": "REPAIR_AUTHORIZATION_REQUIRED"},
            )
        approval, authorization = await self._production._active_budget_approval(
            project_id=project_id,
            workflow_id=workflow.id,
            approval_kind=ApprovalKind.REPAIR_BUDGET,
        )
        if authorization.id != budget_authorization_id:
            raise ConflictError("repair approval uses another budget authorization")
        repair_version, repair_plan, option = await self._repair_context(
            project_id=project_id,
            workflow_artifacts=approval.approved_artifact_versions,
            repair_option_id=repair_option_id,
        )
        if option.estimated_cost is None:
            raise ValidationAppError(
                "repair price is unknown",
                details={"code": "REPAIR_PRICE_UNKNOWN"},
            )
        if option.currency.upper() != authorization.currency.upper():
            raise ValidationAppError(
                "repair price currency differs from the authorization",
                details={"code": "REPAIR_CURRENCY_MISMATCH"},
            )
        if option.estimated_cost > authorization.limit_amount:
            raise ValidationAppError(
                "repair estimate exceeds the authorized budget",
                details={
                    "code": "REPAIR_BUDGET_LIMIT_INSUFFICIENT",
                    "estimated_amount": str(option.estimated_cost),
                    "authorized_limit": str(authorization.limit_amount),
                },
            )
        source_batch = await self._session.get(ProductionBatch, repair_plan.batch_id)
        if (
            source_batch is None
            or source_batch.project_id != project_id
            or source_batch.workflow_run_id != workflow.id
            or source_batch.batch_kind not in {"trial", "production", "repair"}
        ):
            raise ValidationAppError("repair source batch is unavailable")
        artifacts = await self._production._locked_inputs(
            source_batch.locked_version_refs
        )
        storyboard = StoryboardPlanPayload.model_validate(
            artifacts[ArtifactKind.STORYBOARD_PLAN].payload
        )
        character = CharacterBiblePayload.model_validate(
            artifacts[ArtifactKind.CHARACTER_BIBLE].payload
        )
        visual = VisualBiblePayload.model_validate(
            artifacts[ArtifactKind.VISUAL_BIBLE].payload
        )
        voice = VoiceBiblePayload.model_validate(
            artifacts[ArtifactKind.VOICE_BIBLE].payload
        )
        selection = SelectionPlanPayload.model_validate(
            artifacts[ArtifactKind.SELECTION_PLAN].payload
        )
        selected_ids = set(option.affected_shot_ids)
        selected_shots = [shot for shot in storyboard.shots if shot.shot_id in selected_ids]
        if {shot.shot_id for shot in selected_shots} != selected_ids:
            raise ConflictError("repair option references an unknown locked shot")
        locked_refs = dict(source_batch.locked_version_refs)
        locked_refs[ArtifactKind.REPAIR_PLAN.value] = str(repair_version.id)
        batch_hash = content_hash(
            {
                "kind": "repair",
                "source_batch_id": str(source_batch.id),
                "versions": locked_refs,
                "repair_option": option.model_dump(mode="json"),
                "selection": source_batch.selection_snapshot,
                "budget_authorization_id": str(authorization.id),
            }
        )
        root_source_batch_id = (
            str((source_batch.selection_snapshot or {}).get("root_source_batch_id") or "")
            if source_batch.batch_kind == "repair"
            else str(source_batch.id)
        )
        if not root_source_batch_id:
            raise ConflictError("repair source lineage has no root production batch")
        batch = ProductionBatch(
            project_id=project.id,
            workflow_run_id=workflow.id,
            batch_kind="repair",
            idempotency_key=idempotency_key,
            status="materializing",
            budget_authorization_id=authorization.id,
            locked_version_refs=locked_refs,
            selected_shot_ids=[shot.shot_id for shot in selected_shots],
            template_keys=[DIALOGUE_POST_DUB_SHOT_V1],
            quality_policy_id=QUALITY_POLICY_V1,
            selection_snapshot={
                **dict(source_batch.selection_snapshot or {}),
                "repair_option": option.model_dump(mode="json"),
                "source_batch_id": str(source_batch.id),
                "root_source_batch_id": root_source_batch_id,
            },
            semantic_hash=batch_hash,
            created_by=actor.id,
        )
        self._session.add(batch)
        await self._session.flush()
        reservation = BudgetReservation(
            project_id=project.id,
            batch_id=batch.id,
            authorization_id=authorization.id,
            idempotency_key=f"{idempotency_key}:budget",
            reserved_amount=(
                option.estimated_cost
                if option.estimated_cost > 0
                else authorization.limit_amount
            ),
            currency=authorization.currency,
            status="reserved",
        )
        self._session.add(reservation)
        await self._session.flush()
        all_runs: list[NodeRun] = []
        for shot in selected_shots:
            shot_row = await self._production._project_storyboard_shot(
                project=project,
                storyboard=storyboard,
                logical_shot_id=shot.shot_id,
            )
            batch_shot = ProductionBatchShot(
                project_id=project.id,
                batch_id=batch.id,
                logical_shot_id=shot.shot_id,
                shot_id=shot_row.id,
                status="materializing",
                semantic_hash=content_hash(
                    {
                        "source_batch": str(source_batch.id),
                        "source_shot": shot.model_dump(mode="json"),
                        "repair_option": option.model_dump(mode="json"),
                    }
                ),
            )
            self._session.add(batch_shot)
            await self._session.flush()
            runs = await self._production._materialize_shot_graph(
                project=project,
                actor=actor,
                batch=batch,
                reservation=reservation,
                batch_shot=batch_shot,
                storyboard=storyboard,
                shot=shot,
                character=character,
                visual=visual,
                voice=voice,
                selection=selection,
            )
            await self._reuse_unaffected_runs(
                source_batch=source_batch,
                logical_shot_id=shot.shot_id,
                new_runs=runs,
                invalidated=set(option.invalidated_node_keys),
                option=option,
                batch_hash=batch_hash,
            )
            batch_shot.status = "queued"
            all_runs.extend(runs)
        batch.status = "running"
        batch.started_at = datetime.now(UTC)
        self._session.add(
            WorkflowStepRun(
                project_id=project.id,
                workflow_run_id=workflow.id,
                step_key="materialize_repair",
                skill_id="repair_planning",
                skill_version="1.0.0",
                execution_kind="domain_service",
                idempotency_key=f"{idempotency_key}:materialize",
                status="succeeded",
                input_version_refs=[str(repair_version.id)],
                output_version_refs=[],
                service_run_ref=f"repair-batch:{batch.id}",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        for run in all_runs:
            if run.status != "queued":
                continue
            await self._events.append_with_outbox(
                project_id=project.id,
                aggregate_type="production_batch",
                aggregate_id=batch.id,
                event_type="director.node_run.queued",
                topic="node_run.enqueue",
                payload={
                    "node_run_id": str(run.id),
                    "production_batch_id": str(batch.id),
                    "logical_shot_id": str(
                        (run.input_snapshot or {}).get("logical_shot_id") or ""
                    ),
                },
                actor_id=actor.id,
            )
        # Refresh while the project-scoped RLS context still exists. Committing
        # first would clear SET LOCAL and make the row look deleted to refresh.
        await self._session.refresh(batch)
        await self._session.commit()
        return batch, all_runs

    async def _repair_context(
        self,
        *,
        project_id: UUID,
        workflow_artifacts: dict[str, str],
        repair_option_id: str,
    ) -> tuple[CreativeArtifactVersion, RepairPlanPayload, RepairOptionPayload]:
        raw_id = workflow_artifacts.get(ArtifactKind.REPAIR_PLAN.value)
        if raw_id is None:
            raise ValidationAppError("approved repair plan is missing")
        row = await self._session.get(CreativeArtifactVersion, UUID(raw_id))
        if row is None or row.project_id != project_id:
            raise ConflictError("approved repair plan version is missing")
        plan = RepairPlanPayload.model_validate(row.payload)
        option = next(
            (item for item in plan.options if item.repair_option_id == repair_option_id),
            None,
        )
        if option is None:
            raise ValidationAppError("repair option is not part of the approved plan")
        return row, plan, option

    async def _reuse_unaffected_runs(
        self,
        *,
        source_batch: ProductionBatch,
        logical_shot_id: str,
        new_runs: list[NodeRun],
        invalidated: set[str],
        option: RepairOptionPayload,
        batch_hash: str,
    ) -> None:
        source_batch_ids = {source_batch.id}
        source_shot = await self._session.scalar(
            select(ProductionBatchShot).where(
                ProductionBatchShot.batch_id == source_batch.id,
                ProductionBatchShot.logical_shot_id == logical_shot_id,
            )
        )
        if source_shot is not None and source_shot.accepted_node_run_id is not None:
            accepted = await self._session.get(NodeRun, source_shot.accepted_node_run_id)
            if accepted is not None and accepted.production_batch_id is not None:
                source_batch_ids.add(accepted.production_batch_id)
        source_rows = list(
            (
                await self._session.execute(
                    select(NodeRun, GraphNode)
                    .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                    .where(
                        NodeRun.production_batch_id.in_(source_batch_ids),
                        NodeRun.status.in_(_SUCCESS),
                    )
                    .order_by(NodeRun.created_at.desc())
                )
            ).tuples()
        )
        source_by_key: dict[str, NodeRun] = {}
        for source_run, source_node in source_rows:
            if (
                str((source_run.input_snapshot or {}).get("logical_shot_id") or "")
                == logical_shot_id
            ):
                source_by_key.setdefault(source_node.node_key, source_run)
        repair_directive = "；".join(change.summary for change in option.changes)
        for run in new_runs:
            target_node = await self._session.get(GraphNode, run.graph_node_id)
            if target_node is None:
                raise ConflictError("repair graph node is missing")
            if target_node.node_key in invalidated:
                snapshot = dict(run.input_snapshot or {})
                snapshot["repair_option_id"] = option.repair_option_id
                snapshot["repair_directive"] = repair_directive
                if target_node.node_key in {"prompt", "keyframe", "video"}:
                    prompt = str(snapshot.get("prompt") or "")
                    snapshot["prompt"] = f"{prompt}\n定向修复：{repair_directive}"
                run.input_snapshot = snapshot
                run.input_hash = content_hash(
                    {
                        "repair_batch": batch_hash,
                        "node_key": target_node.node_key,
                        "snapshot": snapshot,
                    }
                )
                continue
            reused_source = source_by_key.get(target_node.node_key)
            if reused_source is None:
                # No trustworthy source evidence means recompute, never pretend
                # a cache hit merely to save cost.
                continue
            run.status = "cached"
            run.result_artifact_id = reused_source.result_artifact_id
            run.reused_from_run_id = reused_source.id
            run.output_summary = {
                "status": "cached",
                "reused_from_run_id": str(reused_source.id),
                "repair_option_id": option.repair_option_id,
            }
            run.finished_at = datetime.now(UTC)
