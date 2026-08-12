"""Recoverable Director read model for quick and professional workspaces."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.delivery.models import Export, ExportItem
from app.director.enums import WorkflowStatus
from app.director.models import (
    ApprovalRecord,
    BudgetAuthorization,
    BudgetReservation,
    ChangeProposal,
    CreativeArtifactVersion,
    DirectorIssue,
    ImpactReport,
    ProductionBatch,
    WorkflowStepRun,
)
from app.director.schemas import (
    ApprovalRead,
    ArtifactVersionRead,
    BudgetAuthorizationRead,
    BudgetReservationRead,
    ChangeProposalRead,
    ChangeProposalResult,
    DeliveryItemRead,
    DirectorIssueRead,
    DirectorWorkspaceSnapshot,
    ImpactReportRead,
    LatestDeliveryRead,
    ProductionBatchRead,
    WorkflowRead,
    WorkflowStepRunRead,
)
from app.director.service import DirectorService
from app.execution.models import Artifact

_ALLOWED_ACTIONS: dict[WorkflowStatus, list[str]] = {
    WorkflowStatus.DRAFTING_CREATIVE: ["generate_concepts", "import_script"],
    WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION: [
        "propose_change",
        "confirm_creative_plan",
    ],
    WorkflowStatus.DRAFTING_SHOOTING_PLAN: ["generate_shooting_package"],
    WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION: [
        "propose_change",
        "confirm_shooting_plan",
    ],
    WorkflowStatus.AWAITING_TRIAL_AUTHORIZATION: ["authorize_trial_budget"],
    WorkflowStatus.TRIAL_RUNNING: ["view_trial_progress"],
    WorkflowStatus.AWAITING_TRIAL_REVIEW: ["review_trial"],
    WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION: [
        "authorize_production_budget",
        "request_trial_repair",
    ],
    WorkflowStatus.PRODUCTION_RUNNING: ["view_production_progress"],
    WorkflowStatus.REPAIR_PROPOSED: ["select_repair_option"],
    WorkflowStatus.AWAITING_REPAIR_AUTHORIZATION: ["authorize_repair_budget"],
    WorkflowStatus.ASSEMBLING: ["view_assembly_progress"],
    WorkflowStatus.FINAL_REVIEW: ["export_accepted_production"],
    WorkflowStatus.COMPLETED: ["download_delivery", "open_professional_mode"],
    WorkflowStatus.NEEDS_HUMAN: ["review_evidence", "open_professional_mode"],
    WorkflowStatus.BLOCKED: ["resolve_blocker"],
    WorkflowStatus.CANCELLED: [],
}

_NEXT_ACTION: dict[WorkflowStatus, str] = {
    WorkflowStatus.DRAFTING_CREATIVE: "Choose an entry mode and generate three concepts.",
    WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION: "Review and confirm the creative plan.",
    WorkflowStatus.DRAFTING_SHOOTING_PLAN: "Generate the no-media shooting plan.",
    WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION: "Review risks and confirm the shooting plan.",
    WorkflowStatus.AWAITING_TRIAL_AUTHORIZATION: "Set and authorize a hard trial budget limit.",
    WorkflowStatus.TRIAL_RUNNING: "Wait for the representative shot and evidence.",
    WorkflowStatus.AWAITING_TRIAL_REVIEW: "Review the real trial result.",
    WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION: "Accept the trial and authorize production.",
    WorkflowStatus.PRODUCTION_RUNNING: "Review production progress and failures.",
    WorkflowStatus.REPAIR_PROPOSED: "Choose a targeted repair option.",
    WorkflowStatus.AWAITING_REPAIR_AUTHORIZATION: "Authorize the selected repair budget.",
    WorkflowStatus.ASSEMBLING: "Wait for deterministic delivery assembly.",
    WorkflowStatus.FINAL_REVIEW: "Export the accepted shots in locked story order.",
    WorkflowStatus.COMPLETED: "Download the completed delivery package.",
    WorkflowStatus.NEEDS_HUMAN: "Review insufficient or conflicting quality evidence.",
    WorkflowStatus.BLOCKED: "Resolve the listed configuration or hard quality blocker.",
    WorkflowStatus.CANCELLED: "The workflow is cancelled.",
}


class DirectorSnapshotService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._director = DirectorService(session)

    async def get(self, *, project_id: UUID, actor: User) -> DirectorWorkspaceSnapshot:
        project = await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = await self._director.get_workflow(project_id=project_id, actor=actor)
        artifact_ids = [UUID(value) for value in workflow.current_artifact_versions.values()]
        artifacts = (
            list(
                (
                    await self._session.execute(
                        select(CreativeArtifactVersion).where(
                            CreativeArtifactVersion.id.in_(artifact_ids)
                        )
                    )
                ).scalars()
            )
            if artifact_ids
            else []
        )
        current = {row.artifact_kind: ArtifactVersionRead.model_validate(row) for row in artifacts}
        approvals = list(
            (
                await self._session.execute(
                    select(ApprovalRecord)
                    .where(ApprovalRecord.workflow_run_id == workflow.id)
                    .order_by(ApprovalRecord.approved_at)
                )
            ).scalars()
        )
        authorizations = list(
            (
                await self._session.execute(
                    select(BudgetAuthorization)
                    .where(BudgetAuthorization.workflow_run_id == workflow.id)
                    .order_by(BudgetAuthorization.created_at)
                )
            ).scalars()
        )
        proposals = list(
            (
                await self._session.execute(
                    select(ChangeProposal)
                    .where(
                        ChangeProposal.workflow_run_id == workflow.id,
                        ChangeProposal.status == "awaiting_confirmation",
                    )
                    .order_by(ChangeProposal.created_at)
                )
            ).scalars()
        )
        pending: list[ChangeProposalResult] = []
        for proposal in proposals:
            report = await self._session.scalar(
                select(ImpactReport).where(ImpactReport.change_proposal_id == proposal.id)
            )
            if report is not None:
                pending.append(
                    ChangeProposalResult(
                        proposal=ChangeProposalRead.model_validate(proposal),
                        impact=ImpactReportRead.model_validate(report),
                    )
                )
        issues = list(
            (
                await self._session.execute(
                    select(DirectorIssue)
                    .where(DirectorIssue.workflow_run_id == workflow.id)
                    .order_by(DirectorIssue.created_at)
                )
            ).scalars()
        )
        step_runs = list(
            (
                await self._session.execute(
                    select(WorkflowStepRun)
                    .where(WorkflowStepRun.workflow_run_id == workflow.id)
                    .order_by(WorkflowStepRun.created_at)
                )
            ).scalars()
        )
        batches = list(
            (
                await self._session.execute(
                    select(ProductionBatch)
                    .where(ProductionBatch.workflow_run_id == workflow.id)
                    .order_by(ProductionBatch.created_at)
                )
            ).scalars()
        )
        reservations = list(
            (
                await self._session.execute(
                    select(BudgetReservation)
                    .where(BudgetReservation.project_id == project.id)
                    .order_by(BudgetReservation.created_at)
                )
            ).scalars()
        )
        latest_delivery: LatestDeliveryRead | None = None
        production_batch_ids = {
            str(batch.id) for batch in batches if batch.batch_kind == "production"
        }
        exports = list(
            (
                await self._session.execute(
                    select(Export)
                    .where(Export.project_id == project.id)
                    .order_by(Export.created_at.desc())
                )
            ).scalars()
        )
        delivery_export = next(
            (
                row
                for row in exports
                if str((row.manifest or {}).get("production_batch_id") or "")
                in production_batch_ids
            ),
            None,
        )
        if delivery_export is not None:
            source_items = list(
                (
                    await self._session.execute(
                        select(ExportItem, Artifact)
                        .join(Artifact, Artifact.id == ExportItem.source_artifact_id)
                        .where(ExportItem.export_id == delivery_export.id)
                        .order_by(ExportItem.ordinal)
                    )
                ).tuples()
            )
            manifest = dict(delivery_export.manifest or {})
            items = [
                DeliveryItemRead(
                    kind=item.role,
                    object_key=artifact.object_key,
                    content_hash=artifact.content_hash,
                    byte_size=artifact.byte_size,
                )
                for item, artifact in source_items
            ]
            result_artifact = (
                await self._session.get(Artifact, delivery_export.result_artifact_id)
                if delivery_export.result_artifact_id is not None
                else None
            )
            if result_artifact is not None:
                items.append(
                    DeliveryItemRead(
                        kind="package",
                        object_key=result_artifact.object_key,
                        content_hash=result_artifact.content_hash,
                        byte_size=result_artifact.byte_size,
                    )
                )
            mp4_key = manifest.get("mp4_object_key")
            mp4_hash = manifest.get("mp4_hash")
            if isinstance(mp4_key, str) and isinstance(mp4_hash, str):
                items.append(
                    DeliveryItemRead(
                        kind="program_mp4",
                        object_key=mp4_key,
                        content_hash=mp4_hash,
                        byte_size=0,
                    )
                )
            latest_delivery = LatestDeliveryRead(
                export_id=delivery_export.id,
                status=delivery_export.status,
                items=items,
                program_mp4_error=(
                    str(manifest["mp4_error"])
                    if manifest.get("mp4_error") is not None
                    else None
                ),
            )
        workflow_status = WorkflowStatus(workflow.status)
        return DirectorWorkspaceSnapshot(
            project_id=project.id,
            project_name=project.name,
            aspect_ratio=project.aspect_ratio,
            workflow=WorkflowRead.model_validate(workflow),
            current_artifacts=current,
            approvals=[ApprovalRead.model_validate(item) for item in approvals],
            budget_authorizations=[
                BudgetAuthorizationRead.model_validate(item) for item in authorizations
            ],
            pending_changes=pending,
            issues=[DirectorIssueRead.model_validate(item) for item in issues],
            step_runs=[WorkflowStepRunRead.model_validate(item) for item in step_runs],
            production_batches=[ProductionBatchRead.model_validate(item) for item in batches],
            budget_reservations=[
                BudgetReservationRead.model_validate(item) for item in reservations
            ],
            latest_delivery=latest_delivery,
            allowed_actions=list(_ALLOWED_ACTIONS[workflow_status]),
            next_action=_NEXT_ACTION[workflow_status],
        )
