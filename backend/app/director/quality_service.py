"""Aggregate production evidence without turning one metric into truth."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.director.enums import ApprovalKind, ArtifactKind, WorkflowStatus
from app.director.models import (
    ApprovalRecord,
    CreativeArtifactVersion,
    ProductionBatch,
    ProductionBatchShot,
    WorkflowStepRun,
)
from app.director.service import DirectorService
from app.director.shooting import (
    ProductionQualityReportPayload,
    ProductionReviewPayload,
    QualityDimensionResult,
    QualityReportPayload,
    TrialReviewPayload,
)
from app.director.state_machine import assert_subjective_override_allowed
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.providers.models import ProviderModelBinding, ProviderQualityEvidence
from app.shared.errors import ConflictError, ValidationAppError

_SUCCESS = frozenset({"completed", "cached", "completed_after_cancel"})


def _identity_evidence_status(review_status: str) -> Literal["passed", "needs_human"]:
    """Only an explicit trusted/human decision may report identity as passed."""

    return "passed" if review_status == "passed" else "needs_human"


def _has_frozen_request_evidence(operation: ProviderOperation) -> bool:
    if not operation.request_fingerprint:
        return False
    return operation.actual_provider == "local_tts" or operation.model_binding_id is not None


class DirectorQualityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._director = DirectorService(session)
        self._projects = ProjectService(session)

    async def _record_subjective_override(
        self,
        *,
        project_id: UUID,
        workflow_id: UUID,
        quality_report: CreativeArtifactVersion,
        actor: User,
        review_idempotency_key: str,
        reason: str,
        scopes: list[str],
        hard_block: bool,
    ) -> ApprovalRecord:
        """Persist creator acceptance without mutating automatic quality facts."""
        assert_subjective_override_allowed(hard_block=hard_block)
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValidationAppError(
                "a reason is required to accept subjective quality warnings",
                details={"code": "SUBJECTIVE_OVERRIDE_REASON_REQUIRED"},
            )
        digest = hashlib.sha256(review_idempotency_key.encode("utf-8")).hexdigest()
        override_key = f"subjective-gate:{digest}"
        existing = await self._session.scalar(
            select(ApprovalRecord).where(
                ApprovalRecord.project_id == project_id,
                ApprovalRecord.idempotency_key == override_key,
            )
        )
        if existing is not None:
            return existing
        approval = ApprovalRecord(
            project_id=project_id,
            workflow_run_id=workflow_id,
            approval_kind=ApprovalKind.SUBJECTIVE_GATE_OVERRIDE.value,
            idempotency_key=override_key,
            approved_artifact_versions={ArtifactKind.QUALITY_REPORT.value: str(quality_report.id)},
            reason=f"{clean_reason}\nScope: {', '.join(sorted(scopes))}",
            approved_by=actor.id,
        )
        self._session.add(approval)
        await self._session.flush()
        return approval

    async def inspect_trial(
        self,
        *,
        project_id: UUID,
        batch_id: UUID,
        actor: User,
        idempotency_key: str,
    ) -> CreativeArtifactVersion:
        await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status not in {
            WorkflowStatus.TRIAL_RUNNING.value,
            WorkflowStatus.AWAITING_TRIAL_REVIEW.value,
        }:
            raise ValidationAppError("trial quality inspection is not allowed now")
        existing = await self._director.find_step_run(
            project_id=project_id,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing.status != "succeeded" or len(existing.output_version_refs) != 1:
                raise ConflictError("quality inspection request has an incomplete result")
            rows = await self._director.artifact_versions_by_ids(
                project_id=project_id,
                actor=actor,
                ids=[UUID(existing.output_version_refs[0])],
            )
            if len(rows) != 1:
                raise ConflictError("quality report version is missing")
            return rows[0]
        batch = await self._session.get(ProductionBatch, batch_id)
        if batch is None or batch.project_id != project_id or batch.batch_kind != "trial":
            raise ValidationAppError("trial production batch not found")
        batch_shots = list(
            (
                await self._session.execute(
                    select(ProductionBatchShot).where(ProductionBatchShot.batch_id == batch.id)
                )
            ).scalars()
        )
        if len(batch_shots) != 1:
            raise ConflictError("trial batch must contain exactly one representative shot")
        runs = list(
            (
                await self._session.execute(
                    select(NodeRun, GraphNode)
                    .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                    .where(NodeRun.production_batch_id == batch.id)
                )
            ).tuples()
        )
        by_key = {node.node_key: run for run, node in runs}
        pending = sorted(key for key, run in by_key.items() if run.status in {"queued", "running"})
        if pending:
            raise ValidationAppError(
                "trial production is still running",
                details={"code": "TRIAL_STILL_RUNNING", "node_keys": pending},
            )
        terminal_failures = sorted(
            f"{key}:{run.error_code or run.status}"
            for key, run in by_key.items()
            if run.status not in _SUCCESS
        )
        report = await self._build_report(
            batch=batch,
            batch_shot=batch_shots[0],
            by_key=by_key,
            terminal_failures=terminal_failures,
        )
        version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.QUALITY_REPORT,
            payload=report.model_dump(mode="json"),
            source_kind="service",
            commit=False,
        )
        step = WorkflowStepRun(
            project_id=project_id,
            workflow_run_id=workflow.id,
            step_key="inspect_trial",
            skill_id="quality_inspection",
            skill_version="1.0.0",
            execution_kind="domain_service",
            idempotency_key=idempotency_key,
            status="succeeded",
            input_version_refs=list(batch.locked_version_refs.values()),
            output_version_refs=[str(version.id)],
            service_run_ref=f"quality-report:{version.id}",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        self._session.add(step)
        batch.status = "awaiting_review"
        batch.finished_at = datetime.now(UTC)
        batch_shots[0].status = report.overall_status
        composite = by_key.get("composite")
        if composite is not None and composite.result_artifact_id is not None:
            batch_shots[0].accepted_artifact_id = composite.result_artifact_id
            batch_shots[0].accepted_node_run_id = composite.id
        workflow.status = WorkflowStatus.AWAITING_TRIAL_REVIEW.value
        workflow.current_stage = "trial"
        workflow.version += 1
        await self._session.flush()
        await self._session.refresh(version)
        await self._session.commit()
        return version

    async def review_trial(
        self,
        *,
        project_id: UUID,
        batch_id: UUID,
        decision: Literal["accept", "repair", "stop"],
        user_note: str,
        actor: User,
        idempotency_key: str,
    ) -> CreativeArtifactVersion:
        project = await self._projects.get_project_for_owner(
            project_id=project_id,
            actor=actor,
        )
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status != WorkflowStatus.AWAITING_TRIAL_REVIEW.value:
            raise ValidationAppError("trial is not awaiting creator review")
        existing = await self._director.find_step_run(
            project_id=project_id,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            rows = await self._director.artifact_versions_by_ids(
                project_id=project_id,
                actor=actor,
                ids=[UUID(value) for value in existing.output_version_refs],
            )
            if len(rows) != 1:
                raise ConflictError("trial review result is incomplete")
            return rows[0]
        batch = await self._session.get(ProductionBatch, batch_id)
        if batch is None or batch.project_id != project_id or batch.batch_kind != "trial":
            raise ValidationAppError("trial production batch not found")
        raw_quality_id = workflow.current_artifact_versions.get(ArtifactKind.QUALITY_REPORT.value)
        if raw_quality_id is None:
            raise ValidationAppError("quality report is required before trial review")
        quality = await self._session.get(CreativeArtifactVersion, UUID(raw_quality_id))
        if quality is None:
            raise ConflictError("current quality report is missing")
        quality_payload = QualityReportPayload.model_validate(quality.payload)
        if quality_payload.batch_id != batch.id:
            raise ConflictError("quality report belongs to another trial batch")
        if decision == "accept" and quality_payload.hard_blockers:
            raise ValidationAppError(
                "a trial with hard blockers cannot be accepted",
                details={
                    "code": "HARD_QUALITY_GATE_BLOCKED",
                    "hard_blockers": quality_payload.hard_blockers,
                },
            )
        if decision == "accept" and quality_payload.overall_status in {
            "warning",
            "needs_human",
        }:
            await self._record_subjective_override(
                project_id=project_id,
                workflow_id=workflow.id,
                quality_report=quality,
                actor=actor,
                review_idempotency_key=idempotency_key,
                reason=user_note,
                scopes=[quality_payload.logical_shot_id],
                hard_block=bool(quality_payload.hard_blockers),
            )
        evidence = [
            ref for dimension in quality_payload.dimensions for ref in dimension.evidence_refs
        ]
        payload = TrialReviewPayload(
            batch_id=batch.id,
            quality_report_version_id=quality.id,
            decision=decision,
            accepted_quality=decision == "accept",
            user_note=user_note,
            evidence_refs=list(dict.fromkeys(evidence)),
        )
        version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.TRIAL_REVIEW,
            payload=payload.model_dump(mode="json"),
            source_kind="user",
            commit=False,
        )
        step = WorkflowStepRun(
            project_id=project_id,
            workflow_run_id=workflow.id,
            step_key="review_trial",
            skill_id="quality_inspection",
            skill_version="1.0.0",
            execution_kind="domain_service",
            idempotency_key=idempotency_key,
            status="succeeded",
            input_version_refs=[str(quality.id)],
            output_version_refs=[str(version.id)],
            service_run_ref=f"trial-review:{version.id}",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        self._session.add(step)
        if decision == "accept":
            batch.status = "accepted"
            batch_shot = await self._session.scalar(
                select(ProductionBatchShot).where(ProductionBatchShot.batch_id == batch.id)
            )
            if (
                batch_shot is None
                or batch_shot.accepted_artifact_id is None
                or batch_shot.accepted_node_run_id is None
            ):
                raise ConflictError("accepted trial has no terminal composite evidence")
            batch_shot.status = "accepted"
            await self._promote_trial_model_bindings(
                batch=batch,
                actor=actor,
                workspace_id=project.workspace_id,
            )
            workflow.status = WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION.value
        elif decision == "repair":
            batch.status = "repair_requested"
            workflow.status = WorkflowStatus.REPAIR_PROPOSED.value
        else:
            batch.status = "stopped"
            workflow.status = WorkflowStatus.CANCELLED.value
        workflow.current_stage = "trial" if decision == "accept" else "production"
        workflow.version += 1
        await self._session.flush()
        await self._session.refresh(version)
        await self._session.commit()
        return version

    async def _promote_trial_model_bindings(
        self,
        *,
        batch: ProductionBatch,
        actor: User,
        workspace_id: UUID,
    ) -> None:
        """Turn accepted trial media into immutable binding quality evidence.

        This is the first-install bootstrap path. It uses only successful media
        runs from the accepted representative trial and their exact
        ProviderOperation binding, so a different model's artifact cannot
        promote the selected binding.
        """

        rows = list(
            (
                await self._session.execute(
                    select(NodeRun, GraphNode, ProviderOperation)
                    .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                    .join(
                        ProviderOperation,
                        ProviderOperation.node_run_id == NodeRun.id,
                    )
                    .where(
                        NodeRun.production_batch_id == batch.id,
                        NodeRun.status.in_(_SUCCESS),
                        GraphNode.node_key.in_({"keyframe", "video"}),
                        NodeRun.result_artifact_id.is_not(None),
                        ProviderOperation.status == "succeeded",
                        ProviderOperation.model_binding_id.is_not(None),
                    )
                )
            ).tuples()
        )
        by_node_key = {node.node_key: (run, operation) for run, node, operation in rows}
        missing = sorted({"keyframe", "video"} - set(by_node_key))
        if missing:
            raise ConflictError(
                "accepted trial lacks exact provider quality evidence",
                details={"node_keys": missing},
            )
        for node_key, (run, operation) in by_node_key.items():
            assert operation.model_binding_id is not None
            assert run.result_artifact_id is not None
            binding = await self._session.get(ProviderModelBinding, operation.model_binding_id)
            if binding is None or binding.workspace_id != workspace_id:
                raise ConflictError("trial Provider binding lineage is invalid")
            existing = await self._session.scalar(
                select(ProviderQualityEvidence).where(
                    ProviderQualityEvidence.model_binding_id == binding.id,
                    ProviderQualityEvidence.node_run_id == run.id,
                )
            )
            if existing is None:
                self._session.add(
                    ProviderQualityEvidence(
                        workspace_id=binding.workspace_id,
                        model_binding_id=binding.id,
                        node_run_id=run.id,
                        artifact_id=run.result_artifact_id,
                        evidence_kind=f"creator_accepted_trial_{node_key}",
                        policy_id="creator-accepted-representative-trial-v1",
                        approved_by=actor.id,
                    )
                )
            binding.quality_gated = True
            binding.updated_by = actor.id

    async def inspect_production(
        self,
        *,
        project_id: UUID,
        batch_id: UUID,
        actor: User,
        idempotency_key: str,
    ) -> CreativeArtifactVersion:
        await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status not in {
            WorkflowStatus.PRODUCTION_RUNNING.value,
            WorkflowStatus.FINAL_REVIEW.value,
        }:
            raise ValidationAppError("production quality inspection is not allowed now")
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
                raise ConflictError("production quality report is incomplete")
            return rows[0]
        batch = await self._session.get(ProductionBatch, batch_id)
        if (
            batch is None
            or batch.project_id != project_id
            or batch.batch_kind not in {"production", "repair"}
        ):
            raise ValidationAppError("production batch not found")
        batch_shots = list(
            (
                await self._session.execute(
                    select(ProductionBatchShot)
                    .where(ProductionBatchShot.batch_id == batch.id)
                    .order_by(ProductionBatchShot.logical_shot_id)
                )
            ).scalars()
        )
        if not batch_shots:
            raise ConflictError("production batch has no shots")
        shot_reports: list[QualityReportPayload] = []
        for batch_shot in batch_shots:
            # A semantically identical, creator-accepted trial composite is
            # already reviewed evidence; it is not paid for or judged twice.
            if batch_shot.graph_version_id is None:
                if (
                    batch_shot.status != "accepted"
                    or batch_shot.accepted_artifact_id is None
                    or batch_shot.accepted_node_run_id is None
                ):
                    raise ConflictError("a reused trial shot lacks accepted evidence")
                shot_reports.append(self._reused_trial_report(batch, batch_shot))
                continue
            run_rows = list(
                (
                    await self._session.execute(
                        select(NodeRun, GraphNode)
                        .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                        .where(
                            NodeRun.production_batch_id == batch.id,
                            NodeRun.graph_version_id == batch_shot.graph_version_id,
                        )
                    )
                ).tuples()
            )
            by_key = {node.node_key: run for run, node in run_rows}
            pending = sorted(
                key for key, run in by_key.items() if run.status in {"queued", "running"}
            )
            if pending:
                raise ValidationAppError(
                    "production is still running",
                    details={
                        "code": "PRODUCTION_STILL_RUNNING",
                        "logical_shot_id": batch_shot.logical_shot_id,
                        "node_keys": pending,
                    },
                )
            failures = sorted(
                f"{key}:{run.error_code or run.status}"
                for key, run in by_key.items()
                if run.status not in _SUCCESS
            )
            report = await self._build_report(
                batch=batch,
                batch_shot=batch_shot,
                by_key=by_key,
                terminal_failures=failures,
            )
            composite = by_key.get("composite")
            if composite is not None and composite.result_artifact_id is not None:
                batch_shot.accepted_artifact_id = composite.result_artifact_id
                batch_shot.accepted_node_run_id = composite.id
            batch_shot.status = "blocked" if report.hard_blockers else "ready_for_review"
            shot_reports.append(report)
        hard_blockers = sorted(
            {
                f"{report.logical_shot_id}:{value}"
                for report in shot_reports
                for value in report.hard_blockers
            }
        )
        statuses = {report.overall_status for report in shot_reports}
        overall: Literal["passed", "warning", "needs_human", "blocked"] = (
            "blocked"
            if hard_blockers or "blocked" in statuses
            else "needs_human"
            if "needs_human" in statuses
            else "warning"
            if "warning" in statuses
            else "passed"
        )
        payload = ProductionQualityReportPayload(
            batch_id=batch.id,
            shot_reports=shot_reports,
            overall_status=overall,
            hard_blockers=hard_blockers,
        )
        version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.QUALITY_REPORT,
            payload=payload.model_dump(mode="json"),
            source_kind="service",
            commit=False,
        )
        self._session.add(
            WorkflowStepRun(
                project_id=project_id,
                workflow_run_id=workflow.id,
                step_key="inspect_production",
                skill_id="quality_inspection",
                skill_version="1.0.0",
                execution_kind="domain_service",
                idempotency_key=idempotency_key,
                status="succeeded",
                input_version_refs=list(batch.locked_version_refs.values()),
                output_version_refs=[str(version.id)],
                service_run_ref=f"production-quality-report:{version.id}",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        batch.status = "awaiting_review"
        batch.finished_at = datetime.now(UTC)
        workflow.status = WorkflowStatus.FINAL_REVIEW.value
        workflow.current_stage = "production"
        workflow.version += 1
        await self._session.flush()
        await self._session.refresh(version)
        await self._session.commit()
        return version

    async def review_production(
        self,
        *,
        project_id: UUID,
        batch_id: UUID,
        decisions: dict[str, Literal["accept", "repair", "stop"]],
        user_note: str,
        actor: User,
        idempotency_key: str,
    ) -> CreativeArtifactVersion:
        await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        if workflow.status != WorkflowStatus.FINAL_REVIEW.value:
            raise ValidationAppError("production is not awaiting creator review")
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
                raise ConflictError("production review result is incomplete")
            return rows[0]
        batch = await self._session.get(ProductionBatch, batch_id)
        if (
            batch is None
            or batch.project_id != project_id
            or batch.batch_kind not in {"production", "repair"}
        ):
            raise ValidationAppError("production batch not found")
        shots = list(
            (
                await self._session.execute(
                    select(ProductionBatchShot).where(ProductionBatchShot.batch_id == batch.id)
                )
            ).scalars()
        )
        expected = {shot.logical_shot_id for shot in shots}
        if set(decisions) != expected:
            raise ValidationAppError(
                "one explicit decision is required for every production shot",
                details={"code": "PRODUCTION_REVIEW_INCOMPLETE", "shot_ids": sorted(expected)},
            )
        raw_quality_id = workflow.current_artifact_versions.get(ArtifactKind.QUALITY_REPORT.value)
        if raw_quality_id is None:
            raise ValidationAppError("production quality report is required")
        quality = await self._session.get(CreativeArtifactVersion, UUID(raw_quality_id))
        if quality is None:
            raise ConflictError("production quality report is missing")
        report = ProductionQualityReportPayload.model_validate(quality.payload)
        if report.batch_id != batch.id:
            raise ConflictError("quality report belongs to another production batch")
        blocked_ids = {
            shot_report.logical_shot_id
            for shot_report in report.shot_reports
            if shot_report.hard_blockers
        }
        invalid_accepts = sorted(
            logical_id for logical_id in blocked_ids if decisions.get(logical_id) == "accept"
        )
        if invalid_accepts:
            raise ValidationAppError(
                "shots with hard blockers cannot be accepted",
                details={"code": "HARD_QUALITY_GATE_BLOCKED", "shot_ids": invalid_accepts},
            )
        subjective_accepts = sorted(
            shot_report.logical_shot_id
            for shot_report in report.shot_reports
            if decisions.get(shot_report.logical_shot_id) == "accept"
            and shot_report.overall_status in {"warning", "needs_human"}
        )
        if subjective_accepts:
            await self._record_subjective_override(
                project_id=project_id,
                workflow_id=workflow.id,
                quality_report=quality,
                actor=actor,
                review_idempotency_key=idempotency_key,
                reason=user_note,
                scopes=subjective_accepts,
                hard_block=bool(invalid_accepts),
            )
        for shot in shots:
            decision = decisions[shot.logical_shot_id]
            if decision == "accept":
                if shot.accepted_artifact_id is None or shot.accepted_node_run_id is None:
                    raise ConflictError("accepted shot has no terminal composite evidence")
                shot.status = "accepted"
            elif decision == "repair":
                shot.status = "repair_requested"
            else:
                shot.status = "stopped"
        accepted_ids = sorted(key for key, value in decisions.items() if value == "accept")
        repair_ids = sorted(key for key, value in decisions.items() if value == "repair")
        payload = ProductionReviewPayload(
            batch_id=batch.id,
            quality_report_version_id=quality.id,
            decisions=decisions,
            user_note=user_note,
            accepted_shot_ids=accepted_ids,
            repair_shot_ids=repair_ids,
        )
        version = await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.PRODUCTION_REVIEW,
            payload=payload.model_dump(mode="json"),
            source_kind="user",
            commit=False,
        )
        self._session.add(
            WorkflowStepRun(
                project_id=project_id,
                workflow_run_id=workflow.id,
                step_key="review_production",
                skill_id="quality_inspection",
                skill_version="1.0.0",
                execution_kind="domain_service",
                idempotency_key=idempotency_key,
                status="succeeded",
                input_version_refs=[str(quality.id)],
                output_version_refs=[str(version.id)],
                service_run_ref=f"production-review:{version.id}",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        root_batch = (
            await self._repair_root_batch(batch=batch, project_id=project_id)
            if batch.batch_kind == "repair"
            else batch
        )
        if batch.batch_kind == "repair":
            await self._propagate_repair_acceptances(
                repair_batch=batch,
                root_batch=root_batch,
                repair_shots=shots,
                decisions=decisions,
            )
        if repair_ids:
            batch.status = "repair_requested"
            root_batch.status = "repair_requested"
            workflow.status = WorkflowStatus.REPAIR_PROPOSED.value
        elif any(value == "stop" for value in decisions.values()):
            batch.status = "stopped"
            root_batch.status = "stopped"
            workflow.status = WorkflowStatus.CANCELLED.value
        elif batch.batch_kind == "repair" and root_batch.batch_kind == "trial":
            batch.status = "accepted"
            root_batch.status = "accepted"
            await self._publish_repaired_trial_acceptance(
                project_id=project_id,
                actor=actor,
                root_batch=root_batch,
                quality=quality,
                note=user_note,
            )
            workflow.status = WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION.value
            workflow.current_stage = "trial"
        else:
            batch.status = "accepted"
            root_batch.status = "accepted"
            workflow.status = WorkflowStatus.ASSEMBLING.value
        if not (
            batch.batch_kind == "repair"
            and root_batch.batch_kind == "trial"
            and not repair_ids
            and not any(value == "stop" for value in decisions.values())
        ):
            workflow.current_stage = "production"
        workflow.version += 1
        await self._session.flush()
        await self._session.refresh(version)
        await self._session.commit()
        return version

    async def _repair_root_batch(
        self, *, batch: ProductionBatch, project_id: UUID
    ) -> ProductionBatch:
        raw_root_id = str(
            (batch.selection_snapshot or {}).get("root_source_batch_id")
            or (batch.selection_snapshot or {}).get("source_batch_id")
            or ""
        )
        try:
            root_id = UUID(raw_root_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ConflictError("repair batch root lineage is missing") from exc
        root = await self._session.get(ProductionBatch, root_id)
        if (
            root is None
            or root.project_id != project_id
            or root.workflow_run_id != batch.workflow_run_id
            or root.batch_kind not in {"trial", "production"}
        ):
            raise ConflictError("repair batch root lineage is invalid")
        return root

    async def _propagate_repair_acceptances(
        self,
        *,
        repair_batch: ProductionBatch,
        root_batch: ProductionBatch,
        repair_shots: list[ProductionBatchShot],
        decisions: dict[str, Literal["accept", "repair", "stop"]],
    ) -> None:
        root_shots = {
            row.logical_shot_id: row
            for row in (
                await self._session.execute(
                    select(ProductionBatchShot).where(ProductionBatchShot.batch_id == root_batch.id)
                )
            )
            .scalars()
            .all()
        }
        for repair_shot in repair_shots:
            if decisions[repair_shot.logical_shot_id] != "accept":
                continue
            root_shot = root_shots.get(repair_shot.logical_shot_id)
            if root_shot is None:
                raise ConflictError("repair shot is absent from its root batch")
            if repair_shot.accepted_artifact_id is None or repair_shot.accepted_node_run_id is None:
                raise ConflictError("accepted repair has no composite evidence")
            root_shot.accepted_artifact_id = repair_shot.accepted_artifact_id
            root_shot.accepted_node_run_id = repair_shot.accepted_node_run_id
            root_shot.semantic_hash = repair_shot.semantic_hash
            root_shot.status = "accepted"
        if not any(value == "repair" for value in decisions.values()):
            incomplete = sorted(
                logical_id
                for logical_id, root_shot in root_shots.items()
                if root_shot.status != "accepted"
            )
            if incomplete:
                raise ConflictError(
                    "repair acceptance leaves unresolved root shots",
                    details={"shot_ids": incomplete},
                )
        repair_batch.finished_at = datetime.now(UTC)

    async def _publish_repaired_trial_acceptance(
        self,
        *,
        project_id: UUID,
        actor: User,
        root_batch: ProductionBatch,
        quality: CreativeArtifactVersion,
        note: str,
    ) -> None:
        root_shot = await self._session.scalar(
            select(ProductionBatchShot).where(ProductionBatchShot.batch_id == root_batch.id)
        )
        if (
            root_shot is None
            or root_shot.status != "accepted"
            or root_shot.accepted_artifact_id is None
            or root_shot.accepted_node_run_id is None
        ):
            raise ConflictError("repaired trial has no accepted composite evidence")
        payload = TrialReviewPayload(
            batch_id=root_batch.id,
            quality_report_version_id=quality.id,
            decision="accept",
            accepted_quality=True,
            user_note=note,
            evidence_refs=[
                f"repair-quality-report:{quality.id}",
                f"repair-node-run:{root_shot.accepted_node_run_id}",
                f"repair-artifact:{root_shot.accepted_artifact_id}",
            ],
        )
        await self._director.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind.TRIAL_REVIEW,
            payload=payload.model_dump(mode="json"),
            source_kind="user",
            commit=False,
        )

    @staticmethod
    def _reused_trial_report(
        batch: ProductionBatch, batch_shot: ProductionBatchShot
    ) -> QualityReportPayload:
        evidence = [
            f"trial-node-run:{batch_shot.accepted_node_run_id}",
            f"trial-artifact:{batch_shot.accepted_artifact_id}",
        ]
        dimension_names: tuple[
            Literal[
                "request_contract",
                "identity",
                "technical_integrity",
                "voice_assignment",
                "mouth_motion",
                "continuity",
                "narrative_and_performance",
            ],
            ...,
        ] = (
            "request_contract",
            "identity",
            "technical_integrity",
            "voice_assignment",
            "mouth_motion",
            "continuity",
            "narrative_and_performance",
        )
        dimensions = [
            QualityDimensionResult(
                dimension=dimension,
                status="passed",
                summary="Semantically identical creator-accepted trial evidence was reused.",
                evidence_refs=evidence,
                signals={"reused_accepted_trial": True},
            )
            for dimension in dimension_names
        ]
        return QualityReportPayload(
            batch_id=batch.id,
            logical_shot_id=batch_shot.logical_shot_id,
            overall_status="passed",
            dimensions=dimensions,
            hard_blockers=[],
            limitations=[],
            recommended_action="accept",
        )

    async def _build_report(
        self,
        *,
        batch: ProductionBatch,
        batch_shot: ProductionBatchShot,
        by_key: dict[str, NodeRun],
        terminal_failures: list[str],
    ) -> QualityReportPayload:
        refs = [
            f"node-run:{run.id}" for run in by_key.values() if run.result_artifact_id is not None
        ]
        hard_blockers = list(terminal_failures)
        media_keys = ("keyframe", "video", "voice", "composite")
        missing_media = [
            key for key in media_keys if key not in by_key or by_key[key].result_artifact_id is None
        ]
        hard_blockers.extend(f"missing-artifact:{key}" for key in missing_media)
        provider_ops = list(
            (
                await self._session.execute(
                    select(ProviderOperation).where(
                        ProviderOperation.node_run_id.in_([run.id for run in by_key.values()])
                    )
                )
            ).scalars()
        )
        bad_requests = [str(op.id) for op in provider_ops if not _has_frozen_request_evidence(op)]
        request_status: Literal["passed", "blocked"] = "blocked" if bad_requests else "passed"
        if bad_requests:
            hard_blockers.append("effective-request-evidence-missing")
        identity_review = by_key.get("identity_review")
        identity_review_status = (
            str(
                (identity_review.output_summary or {}).get("identity_review_status")
                or (identity_review.output_summary or {}).get("status")
                or "needs_human"
            )
            if identity_review
            else "blocked"
        )
        identity_signal = dict(identity_review.output_summary or {}) if identity_review else {}
        identity_status = _identity_evidence_status(identity_review_status)
        drift = by_key.get("video_drift_review")
        drift_status = (
            str((drift.output_summary or {}).get("status") or "needs_human") if drift else "blocked"
        )
        continuity = by_key.get("continuity_review")
        continuity_status = (
            str((continuity.output_summary or {}).get("status") or "needs_human")
            if continuity
            else "blocked"
        )
        dimensions = [
            QualityDimensionResult(
                dimension="request_contract",
                status=request_status,
                summary=(
                    "Model binding and effective request fingerprints are persisted."
                    if request_status == "passed"
                    else "One or more media calls lack frozen effective request evidence."
                ),
                evidence_refs=[f"provider-operation:{op.id}" for op in provider_ops],
                signals={
                    "operation_count": len(provider_ops),
                    "invalid_operation_ids": bad_requests,
                },
            ),
            QualityDimensionResult(
                dimension="identity",
                status=identity_status,
                summary=(
                    "Identity was accepted by an audited human or trusted evaluator."
                    if identity_status == "passed"
                    else (
                        "Identity evidence is insufficient or conflicting; "
                        "visual review is required."
                    )
                ),
                evidence_refs=([f"node-run:{identity_review.id}"] if identity_review else []),
                signals={
                    "identity_review_status": identity_review_status,
                    "review_rule": identity_signal.get("review_rule"),
                    "canonical_artifact_id": identity_signal.get("canonical_artifact_id"),
                    "probe_artifact_id": identity_signal.get("probe_artifact_id"),
                    "automatic_identity_decision": identity_signal.get(
                        "automatic_identity_decision", False
                    ),
                    "human_review_required": identity_status != "passed",
                },
            ),
            QualityDimensionResult(
                dimension="technical_integrity",
                status="needs_human" if not hard_blockers else "blocked",
                summary=(
                    "Required media files exist, but severe anatomy or visual "
                    "hallucinations require human review."
                    if not hard_blockers
                    else "Required production artifacts or runs are missing."
                ),
                evidence_refs=refs,
                signals={"missing_media": missing_media},
            ),
            QualityDimensionResult(
                dimension="voice_assignment",
                status="needs_human" if "voice" not in missing_media else "blocked",
                summary=(
                    "Voice bytes exist; speaker ownership and stability require listening review."
                ),
                evidence_refs=[f"node-run:{by_key['voice'].id}"] if "voice" in by_key else [],
            ),
            QualityDimensionResult(
                dimension="mouth_motion",
                status="needs_human" if "video" not in missing_media else "blocked",
                summary=(
                    "No trustworthy automatic lip-sync judge is installed; "
                    "inspect mouth opening and timing."
                ),
                evidence_refs=[f"node-run:{by_key['video'].id}"] if "video" in by_key else [],
            ),
            QualityDimensionResult(
                dimension="continuity",
                status=(
                    "blocked"
                    if continuity_status in {"blocked", "failed"}
                    else "needs_human"
                    if continuity_status == "needs_human"
                    else "warning"
                    if drift_status in {"needs_human", "warning"}
                    else "passed"
                ),
                summary=(
                    "Continuity combines rule checks and frame-drift evidence; "
                    "neither alone approves the shot."
                ),
                evidence_refs=[
                    f"node-run:{run.id}" for run in (drift, continuity) if run is not None
                ],
                signals={
                    "video_drift_status": drift_status,
                    "continuity_status": continuity_status,
                },
            ),
            QualityDimensionResult(
                dimension="narrative_and_performance",
                status="needs_human",
                summary=(
                    "Narrative clarity, acting and visual taste are subjective "
                    "and must be accepted by the creator."
                ),
                evidence_refs=(
                    [f"node-run:{by_key['composite'].id}"] if "composite" in by_key else []
                ),
            ),
        ]
        statuses = {item.status for item in dimensions}
        overall = (
            "blocked"
            if hard_blockers or "blocked" in statuses
            else "needs_human"
            if "needs_human" in statuses
            else "warning"
            if "warning" in statuses
            else "passed"
        )
        return QualityReportPayload(
            batch_id=batch.id,
            logical_shot_id=batch_shot.logical_shot_id,
            overall_status=cast(Literal["passed", "warning", "needs_human", "blocked"], overall),
            dimensions=dimensions,
            hard_blockers=sorted(set(hard_blockers)),
            limitations=[
                "No trusted and calibrated automatic identity evaluator is installed; "
                "character, hair, costume and cross-frame consistency require trial review.",
                "Severe body anomalies, voice quality, mouth motion and acting need human review.",
            ],
            recommended_action="stop" if overall == "blocked" else "review",
        )
