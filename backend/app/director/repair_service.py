"""Evidence-driven repair proposals; no media call occurs in this service."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.director.enums import ArtifactKind, WorkflowStatus
from app.director.models import CreativeArtifactVersion, ProductionBatch, WorkflowStepRun
from app.director.service import DirectorService
from app.director.shooting import (
    CostEstimatePayload,
    ProductionQualityReportPayload,
    ProductionReviewPayload,
    QualityReportPayload,
    RepairChange,
    RepairOptionPayload,
    RepairPlanPayload,
)
from app.execution.models import GraphNode, NodeRun
from app.shared.errors import ConflictError, ValidationAppError

_SUCCESS = frozenset({"completed", "cached", "completed_after_cancel"})


class DirectorRepairService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._director = DirectorService(session)
        self._projects = ProjectService(session)

    async def plan(
        self,
        *,
        project_id: UUID,
        batch_id: UUID,
        quality_report_version_id: UUID,
        actor: User,
        idempotency_key: str,
    ) -> CreativeArtifactVersion:
        await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status != WorkflowStatus.REPAIR_PROPOSED.value:
            raise ValidationAppError("repair planning is not allowed now")
        existing = await self._director.find_step_run(
            project_id=project_id, actor=actor, idempotency_key=idempotency_key
        )
        if existing is not None:
            rows = await self._director.artifact_versions_by_ids(
                project_id=project_id,
                actor=actor,
                ids=[UUID(value) for value in existing.output_version_refs],
            )
            if len(rows) != 1:
                raise ConflictError("repair plan request has an incomplete result")
            return rows[0]
        batch = await self._session.get(ProductionBatch, batch_id)
        quality = await self._session.get(CreativeArtifactVersion, quality_report_version_id)
        if batch is None or batch.project_id != project_id:
            raise ValidationAppError("repair source batch not found")
        if (
            quality is None
            or quality.project_id != project_id
            or quality.artifact_kind != "quality_report"
        ):
            raise ValidationAppError("repair quality report not found")
        reports = self._shot_reports(quality)
        if any(report.batch_id != batch.id for report in reports):
            raise ConflictError("quality report belongs to another production batch")
        report_by_shot = {report.logical_shot_id: report for report in reports}
        raw_production_review_id = workflow.current_artifact_versions.get(
            ArtifactKind.PRODUCTION_REVIEW.value
        )
        if raw_production_review_id is not None:
            review_version = await self._session.get(
                CreativeArtifactVersion, UUID(raw_production_review_id)
            )
            if (
                review_version is None
                or review_version.project_id != project_id
                or review_version.artifact_kind != ArtifactKind.PRODUCTION_REVIEW.value
            ):
                raise ConflictError("production review is missing")
            review = ProductionReviewPayload.model_validate(review_version.payload)
            if review.batch_id != batch.id or review.quality_report_version_id != quality.id:
                raise ConflictError("production review belongs to different quality evidence")
            affected = sorted(review.repair_shot_ids)
            missing_reports = sorted(set(affected) - set(report_by_shot))
            if missing_reports:
                raise ConflictError("repair decisions reference shots outside the quality report")
        else:
            # Trial repair has one representative shot and no production-wide
            # decision map, so its affected scope continues to come from the
            # trial quality evidence.
            affected = sorted(
                report.logical_shot_id
                for report in reports
                if report.overall_status != "passed"
            )
        if not affected:
            raise ValidationAppError("quality evidence does not identify a shot to repair")
        raw_cost_id = workflow.current_artifact_versions.get(
            ArtifactKind.COST_ESTIMATE.value
        )
        cost_version = (
            await self._session.get(CreativeArtifactVersion, UUID(raw_cost_id))
            if raw_cost_id
            else None
        )
        if cost_version is None:
            raise ValidationAppError("repair cost estimate is missing")
        cost = CostEstimatePayload.model_validate(cost_version.payload)
        if cost.repair_total is None or any(line.status != "known" for line in cost.repair):
            raise ValidationAppError(
                "repair price is not verified",
                details={"code": "REPAIR_PRICE_UNKNOWN"},
            )
        strategies = (
            ("video_retry", "model_parameter", "storyboard_simplify")
            if await self._has_reusable_keyframes(batch=batch, affected=affected)
            else ("prompt_reference", "model_parameter", "storyboard_simplify")
        )
        options = [
            self._option(
                batch=batch,
                quality=quality,
                affected=affected,
                reports=report_by_shot,
                strategy=strategy,
                cost=cost,
                currency=cost.currency,
            )
            for strategy in strategies
        ]
        payload = RepairPlanPayload(
            batch_id=batch.id,
            quality_report_version_id=quality.id,
            options=options,
        )
        version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.REPAIR_PLAN,
            payload=payload.model_dump(mode="json"),
            source_kind="service",
            commit=False,
        )
        step = WorkflowStepRun(
            project_id=project_id,
            workflow_run_id=workflow.id,
            step_key="plan_repairs",
            skill_id="repair_planning",
            skill_version="1.0.0",
            execution_kind="domain_service",
            idempotency_key=idempotency_key,
            status="succeeded",
            input_version_refs=[str(quality.id)],
            output_version_refs=[str(version.id)],
            service_run_ref=f"repair-plan:{version.id}",
        )
        self._session.add(step)
        # publish_artifact_version deterministically advances to authorization.
        # Refresh while the transaction-scoped RLS context is still active;
        # committing first clears that context and makes the instance invisible.
        await self._session.flush()
        await self._session.refresh(version)
        await self._session.commit()
        return version

    @staticmethod
    def _shot_reports(
        quality: CreativeArtifactVersion,
    ) -> list[QualityReportPayload]:
        if "shot_reports" in quality.payload:
            return ProductionQualityReportPayload.model_validate(
                quality.payload
            ).shot_reports
        return [QualityReportPayload.model_validate(quality.payload)]

    async def _has_reusable_keyframes(
        self,
        *,
        batch: ProductionBatch,
        affected: list[str],
    ) -> bool:
        rows = (
            await self._session.execute(
                select(NodeRun.input_snapshot)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(
                    NodeRun.production_batch_id == batch.id,
                    NodeRun.status.in_(_SUCCESS),
                    NodeRun.result_artifact_id.is_not(None),
                    GraphNode.node_key == "keyframe",
                )
            )
        ).scalars()
        reusable_shots = {
            str((snapshot or {}).get("logical_shot_id") or "") for snapshot in rows
        }
        return bool(affected) and set(affected).issubset(reusable_shots)

    @staticmethod
    def _option(
        *,
        batch: ProductionBatch,
        quality: CreativeArtifactVersion,
        affected: list[str],
        reports: dict[str, QualityReportPayload],
        strategy: str,
        cost: CostEstimatePayload,
        currency: str,
    ) -> RepairOptionPayload:
        digest = hashlib.sha256(
            f"{batch.id}:{quality.id}:{strategy}:{','.join(affected)}".encode()
        ).hexdigest()[:12]
        summaries = [
            dimension.summary
            for shot_id in affected
            for dimension in reports[shot_id].dimensions
            if dimension.status != "passed"
        ]
        reusable = [
            ref
            for shot_id in affected
            for dimension in reports[shot_id].dimensions
            if dimension.status == "passed"
            for ref in dimension.evidence_refs
        ]
        diagnosis = (
            "；".join(dict.fromkeys(summaries))[:2000]
            or "质量证据需要定向复核。"
        )
        invalidated_by_strategy = {
            "video_retry": [
                "video",
                "video_drift_review",
                "composite",
                "continuity_review",
            ],
            "prompt_reference": [
                "keyframe",
                "identity_review",
                "video",
                "video_drift_review",
                "composite",
                "continuity_review",
            ],
            "model_parameter": [
                "keyframe",
                "identity_review",
                "video",
                "video_drift_review",
                "composite",
                "continuity_review",
            ],
            "storyboard_simplify": [
                "prompt",
                "keyframe",
                "identity_review",
                "video",
                "video_drift_review",
                "subtitle",
                "composite",
                "continuity_review",
            ],
        }
        invalidated = invalidated_by_strategy[strategy]
        paid_purposes = {
            key
            for key in invalidated
            if key in {"keyframe", "video", "voice"}
        }
        repair_prices = {line.purpose: line for line in cost.repair}
        missing_prices = sorted(paid_purposes - set(repair_prices))
        if missing_prices:
            raise ValidationAppError(
                "repair price snapshot does not cover the invalidated media nodes",
                details={
                    "code": "REPAIR_PRICE_UNKNOWN",
                    "purposes": missing_prices,
                },
            )
        estimated_cost = sum(
            (
                repair_prices[purpose].unit_amount or Decimal("0")
                for purpose in paid_purposes
            ),
            start=Decimal("0"),
        ) * len(affected)
        if strategy == "video_retry":
            return RepairOptionPayload(
                repair_option_id=f"repair-{digest}",
                title="复用成功关键帧，仅重试视频",
                invalidated_node_keys=invalidated,
                changes=[
                    RepairChange(
                        target="parameter",
                        summary="保留已成功关键帧，只重新提交视频并重跑真实下游",
                    )
                ],
                estimated_cost=estimated_cost,
                affected_shot_ids=affected,
                reusable_artifact_ids=reusable,
                currency=currency,
                estimated_time_seconds=None,
                diagnosis=diagnosis,
                residual_risks=["供应商仍可能暂时不可用；人物与表演仍需人工验收"],
            )
        if strategy == "prompt_reference":
            return RepairOptionPayload(
                repair_option_id=f"repair-{digest}",
                title="强化角色锚点并重写镜头提示",
                invalidated_node_keys=invalidated,
                changes=[
                    RepairChange(
                        target="reference", summary="重新注入已锁定的虚构角色参考图"
                    ),
                    RepairChange(
                        target="prompt", summary="删去冲突外观词并强调镜头连续性"
                    ),
                ],
                estimated_cost=estimated_cost,
                affected_shot_ids=affected,
                reusable_artifact_ids=reusable,
                currency=currency,
                estimated_time_seconds=None,
                diagnosis=diagnosis,
                residual_risks=["复杂肢体与主观表演仍需人工验收"],
            )
        if strategy == "model_parameter":
            return RepairOptionPayload(
                repair_option_id=f"repair-{digest}",
                title="更换已验证模型或保守参数",
                invalidated_node_keys=invalidated,
                changes=[
                    RepairChange(
                        target="model",
                        summary="仅允许切换到能力档案满足当前镜头的已配置模型",
                    ),
                    RepairChange(
                        target="parameter", summary="使用供应商能力清单支持的保守原生参数"
                    ),
                ],
                estimated_cost=estimated_cost,
                affected_shot_ids=affected,
                reusable_artifact_ids=reusable,
                currency=currency,
                estimated_time_seconds=None,
                diagnosis=diagnosis,
                residual_risks=["新模型必须先完成能力与价格预检"],
            )
        return RepairOptionPayload(
            repair_option_id=f"repair-{digest}",
            title="简化高风险分镜",
            invalidated_node_keys=invalidated,
            changes=[
                RepairChange(
                    target="storyboard",
                    summary="将多人、复杂动作或快速机位改为可执行的单人镜头",
                )
            ],
            estimated_cost=estimated_cost,
            affected_shot_ids=affected,
            reusable_artifact_ids=reusable,
            currency=currency,
            estimated_time_seconds=None,
            diagnosis=diagnosis,
            residual_risks=["修改锁定分镜前必须展示影响并再次确认"],
        )
