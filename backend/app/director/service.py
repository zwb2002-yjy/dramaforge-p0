"""Command-oriented application service for the controlled AI Director."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.director.creative import validate_creative_artifact_payload
from app.director.enums import (
    ApprovalKind,
    ArtifactKind,
    AuthorizationStatus,
    ProposalStatus,
    WorkflowStatus,
)
from app.director.models import (
    ApprovalRecord,
    BudgetAuthorization,
    BudgetReservation,
    ChangeProposal,
    CreativeArtifactVersion,
    DirectorWorkflowRun,
    ImpactReport,
    ProductionBatch,
    WorkflowStepRun,
)
from app.director.registry import get_template
from app.director.state_machine import status_after_approval
from app.execution.models import NodeRun
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

_CHANGE_PROPOSAL_STATUSES = {
    WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION.value,
    WorkflowStatus.DRAFTING_SHOOTING_PLAN.value,
    WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION.value,
    WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION.value,
    WorkflowStatus.REPAIR_PROPOSED.value,
    WorkflowStatus.AWAITING_REPAIR_AUTHORIZATION.value,
    WorkflowStatus.FINAL_REVIEW.value,
    WorkflowStatus.COMPLETED.value,
}

_STATIC_BATCH_STATUSES = {
    "accepted",
    "awaiting_review",
    "repair_requested",
    "stopped",
    "completed",
    "superseded_by_change",
}
_ACTIVE_NODE_RUN_STATUSES = {"queued", "running"}


def content_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """SQLite drops timezone offsets; normalize persisted values for comparisons."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class DirectorService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)

    async def start_workflow(
        self,
        *,
        project_id: UUID,
        actor: User,
        template_id: str = "live_action_dialogue_short",
        template_version: str = "1.0.0",
    ) -> DirectorWorkflowRun:
        await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        template = get_template(template_id, template_version)
        existing = await self._workflow_or_none(project_id)
        if existing is not None:
            if (
                existing.template_id != template.template_id
                or existing.template_version != template.version
            ):
                raise ConflictError("project already uses another workflow template")
            return existing
        workflow = DirectorWorkflowRun(
            project_id=project_id,
            template_id=template.template_id,
            template_version=template.version,
            status=WorkflowStatus.DRAFTING_CREATIVE.value,
            current_stage="creative",
            current_artifact_versions={},
            created_by=actor.id,
        )
        self._session.add(workflow)
        await self._session.commit()
        await self._session.refresh(workflow)
        return workflow

    async def get_workflow(
        self, *, project_id: UUID, actor: User, for_update: bool = False
    ) -> DirectorWorkflowRun:
        await self._projects.get_project_for_owner(project_id=project_id, actor=actor)
        workflow = (
            await self._locked_workflow(project_id=project_id)
            if for_update
            else await self._workflow_or_none(project_id)
        )
        if workflow is None:
            raise NotFoundError("director workflow not found")
        return workflow

    async def publish_artifact_version(
        self,
        *,
        project_id: UUID,
        actor: User,
        artifact_kind: ArtifactKind,
        payload: dict[str, object],
        source_kind: str,
        source_run_id: UUID | None = None,
        commit: bool = True,
        confirmed_change: bool = False,
    ) -> CreativeArtifactVersion:
        workflow = await self.get_workflow(project_id=project_id, actor=actor, for_update=True)
        if source_kind not in {"user", "agent", "imported", "service"}:
            raise ValidationAppError("unsupported artifact source_kind")
        if not confirmed_change:
            await self._assert_no_pending_changes(workflow)
            self._assert_artifact_allowed(workflow, artifact_kind)
        payload = validate_creative_artifact_payload(artifact_kind.value, payload)
        digest = content_hash(payload)
        existing = (
            await self._session.execute(
                select(CreativeArtifactVersion).where(
                    CreativeArtifactVersion.project_id == project_id,
                    CreativeArtifactVersion.artifact_kind == artifact_kind.value,
                    CreativeArtifactVersion.content_hash == digest,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        current_id = workflow.current_artifact_versions.get(artifact_kind.value)
        current_uuid = UUID(current_id) if current_id else None
        if current_uuid is not None:
            current_version = await self._session.get(CreativeArtifactVersion, current_uuid)
            if current_version is None:
                raise ConflictError("current creative artifact version is missing")
            if current_version.status == "locked" and not confirmed_change:
                raise ConflictError(
                    "locked content must be changed through a confirmed change proposal",
                    details={"code": "LOCKED_CONTENT_REQUIRES_PROPOSAL"},
                )
        max_revision = await self._session.scalar(
            select(func.max(CreativeArtifactVersion.revision_no)).where(
                CreativeArtifactVersion.project_id == project_id,
                CreativeArtifactVersion.artifact_kind == artifact_kind.value,
            )
        )
        version = CreativeArtifactVersion(
            project_id=project_id,
            workflow_run_id=workflow.id,
            artifact_kind=artifact_kind.value,
            revision_no=int(max_revision or 0) + 1,
            supersedes_version_id=current_uuid,
            source_kind=source_kind,
            source_run_id=source_run_id,
            payload=payload,
            content_hash=digest,
            status="draft",
            created_by=actor.id,
        )
        self._session.add(version)
        await self._session.flush()
        workflow.current_artifact_versions = {
            **workflow.current_artifact_versions,
            artifact_kind.value: str(version.id),
        }
        workflow.version += 1
        if artifact_kind in {
            ArtifactKind.EPISODE_SCRIPT,
            ArtifactKind.STORY_REVIEW,
        }:
            workflow.status = WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION.value
        if artifact_kind in {
            ArtifactKind.STORYBOARD_PLAN,
            ArtifactKind.RISK_REPORT,
            ArtifactKind.SELECTION_PLAN,
            ArtifactKind.COST_ESTIMATE,
        }:
            workflow.status = WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION.value
            workflow.current_stage = "shooting"
        if artifact_kind == ArtifactKind.TRIAL_REVIEW:
            if workflow.status not in {
                WorkflowStatus.TRIAL_RUNNING.value,
                WorkflowStatus.AWAITING_TRIAL_REVIEW.value,
                WorkflowStatus.FINAL_REVIEW.value,
            }:
                raise ValidationAppError(
                    "trial review is not allowed in the current workflow state"
                )
            workflow.status = WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION.value
            workflow.current_stage = "trial"
        if artifact_kind == ArtifactKind.REPAIR_PLAN:
            if workflow.status not in {
                WorkflowStatus.PRODUCTION_RUNNING.value,
                WorkflowStatus.REPAIR_PROPOSED.value,
            }:
                raise ValidationAppError("repair plan is not allowed in the current workflow state")
            workflow.status = WorkflowStatus.AWAITING_REPAIR_AUTHORIZATION.value
            workflow.current_stage = "production"
        if commit:
            await self._session.commit()
            await self._session.refresh(version)
        return version

    async def approve(
        self,
        *,
        project_id: UUID,
        actor: User,
        approval_kind: ApprovalKind,
        idempotency_key: str,
        reason: str | None = None,
        budget_authorization_id: UUID | None = None,
    ) -> tuple[ApprovalRecord, DirectorWorkflowRun]:
        if not idempotency_key.strip():
            raise ValidationAppError("idempotency_key is required")
        workflow = await self.get_workflow(project_id=project_id, actor=actor, for_update=True)
        existing = (
            await self._session.execute(
                select(ApprovalRecord).where(
                    ApprovalRecord.project_id == project_id,
                    ApprovalRecord.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.approval_kind != approval_kind.value:
                raise ConflictError("idempotency key was reused for another approval")
            return existing, workflow
        await self._assert_no_pending_changes(workflow)
        self._assert_required_artifacts(workflow, approval_kind)
        next_status = status_after_approval(workflow.status, approval_kind)
        if approval_kind in {
            ApprovalKind.TRIAL_BUDGET,
            ApprovalKind.PRODUCTION_BUDGET,
            ApprovalKind.REPAIR_BUDGET,
        }:
            authorization = await self._require_active_authorization(
                project_id=project_id,
                authorization_id=budget_authorization_id,
                expected_kind=approval_kind,
            )
            budget_authorization_id = authorization.id
        approval = ApprovalRecord(
            project_id=project_id,
            workflow_run_id=workflow.id,
            approval_kind=approval_kind.value,
            idempotency_key=idempotency_key,
            approved_artifact_versions=dict(workflow.current_artifact_versions),
            budget_authorization_id=budget_authorization_id,
            reason=reason,
            approved_by=actor.id,
        )
        self._session.add(approval)
        await self._session.flush()
        if approval_kind in {ApprovalKind.CREATIVE_PLAN, ApprovalKind.SHOOTING_PLAN}:
            await self._lock_current_versions(workflow)
        workflow.status = next_status.value
        workflow.current_stage = {
            ApprovalKind.CREATIVE_PLAN: "shooting",
            ApprovalKind.SHOOTING_PLAN: "trial",
            ApprovalKind.TRIAL_BUDGET: "trial",
            ApprovalKind.PRODUCTION_BUDGET: "production",
            ApprovalKind.REPAIR_BUDGET: "production",
        }.get(approval_kind, workflow.current_stage)
        workflow.version += 1
        await self._session.commit()
        await self._session.refresh(approval)
        return approval, workflow

    async def authorize_budget(
        self,
        *,
        project_id: UUID,
        actor: User,
        authorization_kind: ApprovalKind,
        idempotency_key: str,
        pricing_snapshot_id: str,
        limit_amount: Decimal,
        currency: str,
        expires_at: datetime,
    ) -> BudgetAuthorization:
        if authorization_kind not in {
            ApprovalKind.TRIAL_BUDGET,
            ApprovalKind.PRODUCTION_BUDGET,
            ApprovalKind.REPAIR_BUDGET,
        }:
            raise ValidationAppError("authorization_kind is not a budget authorization")
        if limit_amount <= 0:
            raise ValidationAppError("limit_amount must be greater than zero")
        if expires_at <= datetime.now(UTC):
            raise ValidationAppError("budget authorization must expire in the future")
        workflow = await self.get_workflow(project_id=project_id, actor=actor, for_update=True)
        allowed_status = {
            ApprovalKind.TRIAL_BUDGET: WorkflowStatus.AWAITING_TRIAL_AUTHORIZATION,
            ApprovalKind.PRODUCTION_BUDGET: WorkflowStatus.AWAITING_PRODUCTION_AUTHORIZATION,
            ApprovalKind.REPAIR_BUDGET: WorkflowStatus.AWAITING_REPAIR_AUTHORIZATION,
        }[authorization_kind]
        if workflow.status != allowed_status.value:
            raise ValidationAppError(
                "budget authorization is not allowed in the current workflow state",
                details={
                    "code": "BUDGET_AUTHORIZATION_NOT_ALLOWED",
                    "current_status": workflow.status,
                    "authorization_kind": authorization_kind.value,
                },
            )
        await self._assert_no_pending_changes(workflow)
        existing = (
            await self._session.execute(
                select(BudgetAuthorization).where(
                    BudgetAuthorization.project_id == project_id,
                    BudgetAuthorization.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.authorization_kind != authorization_kind.value
                or existing.limit_amount != limit_amount
                or existing.currency != currency.upper()
            ):
                raise ConflictError("idempotency key was reused with another budget")
            return existing
        auth = BudgetAuthorization(
            project_id=project_id,
            workflow_run_id=workflow.id,
            authorization_kind=authorization_kind.value,
            idempotency_key=idempotency_key,
            pricing_snapshot_id=pricing_snapshot_id,
            limit_amount=limit_amount,
            consumed_amount=Decimal("0"),
            currency=currency.upper(),
            status=AuthorizationStatus.ACTIVE.value,
            authorized_by=actor.id,
            expires_at=expires_at,
        )
        self._session.add(auth)
        await self._session.commit()
        await self._session.refresh(auth)
        return auth

    async def propose_change(
        self,
        *,
        project_id: UUID,
        actor: User,
        idempotency_key: str,
        target_artifact_kind: ArtifactKind,
        summary: str,
        replacement_payload: dict[str, object],
    ) -> tuple[ChangeProposal, ImpactReport]:
        workflow = await self.get_workflow(project_id=project_id, actor=actor, for_update=True)
        existing = (
            await self._session.execute(
                select(ChangeProposal).where(
                    ChangeProposal.project_id == project_id,
                    ChangeProposal.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            report = (
                await self._session.execute(
                    select(ImpactReport).where(ImpactReport.change_proposal_id == existing.id)
                )
            ).scalar_one()
            return existing, report
        self._assert_change_allowed(workflow, action="proposal")
        await self._assert_no_pending_changes(workflow)
        batches, reservations = await self._assert_post_media_change_safe(
            project_id=project_id,
            workflow=workflow,
        )
        base_text = workflow.current_artifact_versions.get(target_artifact_kind.value)
        if base_text is None:
            raise ValidationAppError(
                "change proposals require a current artifact version",
                details={
                    "code": "CHANGE_TARGET_NOT_CURRENT",
                    "artifact_kind": target_artifact_kind.value,
                },
            )
        replacement_payload = validate_creative_artifact_payload(
            target_artifact_kind.value, replacement_payload
        )
        base_id = UUID(base_text)
        invalidated = self._downstream_version_ids(
            workflow.current_artifact_versions, target_artifact_kind
        )
        affected_shot_ids = sorted(
            {shot_id for batch in batches for shot_id in batch.selected_shot_ids}
        )
        settled_amount = sum(
            (Decimal(str(reservation.actual_amount or 0)) for reservation in reservations),
            Decimal("0"),
        )
        releasable = [
            str(reservation.id)
            for reservation in reservations
            if reservation.status == "reserved" and reservation.actual_amount is None
        ]
        proposal = ChangeProposal(
            project_id=project_id,
            workflow_run_id=workflow.id,
            idempotency_key=idempotency_key,
            target_artifact_kind=target_artifact_kind.value,
            base_version_id=base_id,
            summary=summary,
            replacement_payload=replacement_payload,
            status=ProposalStatus.AWAITING_CONFIRMATION.value,
            proposed_by=actor.id,
        )
        self._session.add(proposal)
        await self._session.flush()
        report = ImpactReport(
            project_id=project_id,
            workflow_run_id=workflow.id,
            change_proposal_id=proposal.id,
            invalidated_version_ids=invalidated,
            affected_shot_ids=affected_shot_ids,
            reusable_artifact_ids=[],
            estimated_added_cost=None,
            estimated_added_time_seconds=None,
            details={
                "requires_confirmation": True,
                "cost_status": "unknown_until_selection_plan",
                "scope_status": (
                    "historical_media_lineage_will_be_superseded"
                    if batches
                    else "project_artifact_dependencies_only"
                ),
                "affected_batch_ids": [str(batch.id) for batch in batches],
                "releasable_reservation_ids": releasable,
                "historical_settled_amount": str(settled_amount),
                "historical_currencies": sorted(
                    {reservation.currency.upper() for reservation in reservations}
                ),
                "media_reuse_policy": (
                    "none_until_regenerated_and_reapproved"
                    if batches
                    else "not_applicable"
                ),
            },
        )
        self._session.add(report)
        await self._session.commit()
        await self._session.refresh(proposal)
        await self._session.refresh(report)
        return proposal, report

    async def apply_change(
        self, *, project_id: UUID, proposal_id: UUID, actor: User
    ) -> CreativeArtifactVersion:
        workflow = await self.get_workflow(project_id=project_id, actor=actor, for_update=True)
        proposal = await self._session.scalar(
            select(ChangeProposal)
            .where(ChangeProposal.id == proposal_id)
            .with_for_update()
        )
        if proposal is None or proposal.project_id != project_id:
            raise NotFoundError("change proposal not found")
        if proposal.status == ProposalStatus.APPLIED.value:
            current_id = workflow.current_artifact_versions.get(proposal.target_artifact_kind)
            if current_id is None:
                raise ConflictError("applied proposal has no current artifact version")
            version = await self._session.get(CreativeArtifactVersion, UUID(current_id))
            if version is None:
                raise ConflictError("applied proposal artifact version is missing")
            return version
        if proposal.status != ProposalStatus.AWAITING_CONFIRMATION.value:
            raise ConflictError("change proposal is not awaiting confirmation")
        self._assert_change_allowed(workflow, action="confirmation")
        batches, reservations = await self._assert_post_media_change_safe(
            project_id=project_id,
            workflow=workflow,
            lock=True,
        )
        if workflow.current_artifact_versions.get(proposal.target_artifact_kind) != (
            str(proposal.base_version_id) if proposal.base_version_id else None
        ):
            raise ConflictError("change proposal base version is stale")
        report = (
            await self._session.execute(
                select(ImpactReport).where(ImpactReport.change_proposal_id == proposal.id)
            )
        ).scalar_one()
        now = datetime.now(UTC)
        if report.invalidated_version_ids:
            rows = list(
                (
                    await self._session.execute(
                        select(CreativeArtifactVersion).where(
                            CreativeArtifactVersion.id.in_(
                                [UUID(value) for value in report.invalidated_version_ids]
                            )
                        )
                    )
                ).scalars()
            )
            for row in rows:
                row.status = "superseded"
            approvals = list(
                (
                    await self._session.execute(
                        select(ApprovalRecord).where(
                            ApprovalRecord.project_id == project_id,
                            ApprovalRecord.invalidated_at.is_(None),
                        )
                    )
                ).scalars()
            )
            for approval in approvals:
                if any(
                    version_id in report.invalidated_version_ids
                    for version_id in approval.approved_artifact_versions.values()
                ):
                    approval.invalidated_at = now
                    approval.invalidated_by_proposal_id = proposal.id
            invalidated_set = set(report.invalidated_version_ids)
            workflow.current_artifact_versions = {
                kind: version_id
                for kind, version_id in workflow.current_artifact_versions.items()
                if version_id not in invalidated_set
            }
        if batches:
            await self._supersede_static_media_lineage(
                proposal=proposal,
                batches=batches,
                reservations=reservations,
                now=now,
            )
        version = await self.publish_artifact_version(
            project_id=project_id,
            actor=actor,
            artifact_kind=ArtifactKind(proposal.target_artifact_kind),
            payload=proposal.replacement_payload,
            source_kind="user",
            commit=False,
            confirmed_change=True,
        )
        proposal.status = ProposalStatus.APPLIED.value
        proposal.applied_at = now
        workflow = await self.get_workflow(project_id=project_id, actor=actor)
        workflow.status = self._rollback_status(ArtifactKind(proposal.target_artifact_kind)).value
        workflow.current_stage = (
            "creative"
            if workflow.status == WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION.value
            else "shooting"
        )
        workflow.version += 1
        await self._session.commit()
        return version

    async def find_step_run(
        self,
        *,
        project_id: UUID,
        actor: User,
        idempotency_key: str,
    ) -> WorkflowStepRun | None:
        workflow = await self.get_workflow(project_id=project_id, actor=actor)
        return (
            await self._session.execute(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id == workflow.id,
                    WorkflowStepRun.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    async def artifact_versions_by_ids(
        self, *, project_id: UUID, ids: list[UUID], actor: User
    ) -> list[CreativeArtifactVersion]:
        await self.get_workflow(project_id=project_id, actor=actor)
        if not ids:
            return []
        rows = list(
            (
                await self._session.execute(
                    select(CreativeArtifactVersion).where(
                        CreativeArtifactVersion.project_id == project_id,
                        CreativeArtifactVersion.id.in_(ids),
                    )
                )
            ).scalars()
        )
        by_id = {row.id: row for row in rows}
        return [by_id[value] for value in ids if value in by_id]

    async def _workflow_or_none(self, project_id: UUID) -> DirectorWorkflowRun | None:
        return (
            await self._session.execute(
                select(DirectorWorkflowRun).where(DirectorWorkflowRun.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def _locked_workflow(self, *, project_id: UUID) -> DirectorWorkflowRun | None:
        return cast(
            DirectorWorkflowRun | None,
            await self._session.scalar(
                select(DirectorWorkflowRun)
                .where(DirectorWorkflowRun.project_id == project_id)
                .with_for_update()
            ),
        )

    async def _lock_current_versions(self, workflow: DirectorWorkflowRun) -> None:
        ids = [UUID(value) for value in workflow.current_artifact_versions.values()]
        if not ids:
            raise ValidationAppError("there are no artifact versions to approve")
        rows = list(
            (
                await self._session.execute(
                    select(CreativeArtifactVersion).where(CreativeArtifactVersion.id.in_(ids))
                )
            ).scalars()
        )
        now = datetime.now(UTC)
        for row in rows:
            row.status = "locked"
            row.locked_at = now

    async def _assert_no_pending_changes(self, workflow: DirectorWorkflowRun) -> None:
        pending = await self._session.scalar(
            select(func.count(ChangeProposal.id)).where(
                ChangeProposal.workflow_run_id == workflow.id,
                ChangeProposal.status == ProposalStatus.AWAITING_CONFIRMATION.value,
            )
        )
        if pending:
            raise ValidationAppError(
                "pending change proposals must be confirmed before approval",
                details={
                    "code": "PENDING_CHANGE_REQUIRES_CONFIRMATION",
                    "pending_change_count": int(pending),
                },
            )

    async def _assert_post_media_change_safe(
        self,
        *,
        project_id: UUID,
        workflow: DirectorWorkflowRun,
        lock: bool = False,
    ) -> tuple[list[ProductionBatch], list[BudgetReservation]]:
        batch_query = (
            select(ProductionBatch)
            .where(ProductionBatch.workflow_run_id == workflow.id)
            .order_by(ProductionBatch.created_at)
        )
        if lock:
            batch_query = batch_query.with_for_update()
        batches = list(
            (
                await self._session.execute(batch_query)
            ).scalars()
        )
        non_static = [batch for batch in batches if batch.status not in _STATIC_BATCH_STATUSES]
        if non_static:
            raise ValidationAppError(
                "content changes are blocked while media batches are active",
                details={
                    "code": "POST_MEDIA_CHANGE_ACTIVE_BATCH",
                    "batch_ids": [str(batch.id) for batch in non_static],
                    "batch_statuses": [batch.status for batch in non_static],
                },
            )
        batch_ids = [batch.id for batch in batches]
        if batch_ids:
            run_query = select(NodeRun).where(
                NodeRun.production_batch_id.in_(batch_ids),
                NodeRun.status.in_(_ACTIVE_NODE_RUN_STATUSES),
            )
            if lock:
                run_query = run_query.with_for_update()
            active_runs = list(
                (
                    await self._session.execute(run_query)
                ).scalars()
            )
            if active_runs:
                raise ValidationAppError(
                    "content changes are blocked while media nodes are active",
                    details={
                        "code": "POST_MEDIA_CHANGE_ACTIVE_NODE_RUN",
                        "node_run_ids": [str(run.id) for run in active_runs],
                    },
                )
        if not batches:
            return batches, []
        reservation_query = (
            select(BudgetReservation)
            .where(
                BudgetReservation.project_id == project_id,
                BudgetReservation.batch_id.in_(batch_ids),
            )
            .order_by(BudgetReservation.created_at)
        )
        if lock:
            reservation_query = reservation_query.with_for_update()
        reservations = list((await self._session.execute(reservation_query)).scalars())
        return batches, reservations

    async def _supersede_static_media_lineage(
        self,
        *,
        proposal: ChangeProposal,
        batches: list[ProductionBatch],
        reservations: list[BudgetReservation],
        now: datetime,
    ) -> None:
        batch_ids = {batch.id for batch in batches}
        authorization_ids = {batch.budget_authorization_id for batch in batches}
        for batch in batches:
            batch.status = "superseded_by_change"
            batch.finished_at = batch.finished_at or now
        for reservation in reservations:
            if (
                reservation.batch_id in batch_ids
                and reservation.status == "reserved"
                and reservation.actual_amount is None
            ):
                reservation.status = "released"
                reservation.settled_at = now
        authorizations = list(
            (
                await self._session.execute(
                    select(BudgetAuthorization)
                    .where(BudgetAuthorization.id.in_(authorization_ids))
                    .with_for_update()
                )
            ).scalars()
        )
        for authorization in authorizations:
            if authorization.status == AuthorizationStatus.ACTIVE.value:
                authorization.status = AuthorizationStatus.REVOKED.value
        approvals = list(
            (
                await self._session.execute(
                    select(ApprovalRecord).where(
                        ApprovalRecord.workflow_run_id == proposal.workflow_run_id,
                        ApprovalRecord.invalidated_at.is_(None),
                    ).with_for_update()
                )
            ).scalars()
        )
        for approval in approvals:
            if approval.budget_authorization_id in authorization_ids:
                approval.invalidated_at = now
                approval.invalidated_by_proposal_id = proposal.id

    @staticmethod
    def _assert_change_allowed(workflow: DirectorWorkflowRun, *, action: str) -> None:
        if workflow.status in _CHANGE_PROPOSAL_STATUSES:
            return
        code = (
            "CHANGE_PROPOSAL_NOT_ALLOWED"
            if action == "proposal"
            else "CHANGE_CONFIRMATION_NOT_ALLOWED"
        )
        raise ValidationAppError(
            f"change {action} is not allowed in the current workflow state",
            details={"code": code, "current_status": workflow.status},
        )


    async def _require_active_authorization(
        self,
        *,
        project_id: UUID,
        authorization_id: UUID | None,
        expected_kind: ApprovalKind,
    ) -> BudgetAuthorization:
        if authorization_id is None:
            raise ValidationAppError("budget authorization is required")
        authorization = await self._session.get(BudgetAuthorization, authorization_id)
        if authorization is None or authorization.project_id != project_id:
            raise NotFoundError("budget authorization not found")
        if authorization.authorization_kind != expected_kind.value:
            raise ValidationAppError("budget authorization kind does not match approval")
        if authorization.status != AuthorizationStatus.ACTIVE.value or _as_utc(
            authorization.expires_at
        ) <= datetime.now(UTC):
            raise ValidationAppError("budget authorization is not active")
        return authorization

    @staticmethod
    def _downstream_version_ids(current: dict[str, str], target: ArtifactKind) -> list[str]:
        order = [
            ArtifactKind.PREFERENCE_UNDERSTANDING,
            ArtifactKind.CONCEPT_SET,
            ArtifactKind.STORY_CORE,
            ArtifactKind.SEASON_PLAN,
            ArtifactKind.EPISODE_SCRIPT,
            ArtifactKind.STORY_REVIEW,
            ArtifactKind.CHARACTER_BIBLE,
            ArtifactKind.VISUAL_BIBLE,
            ArtifactKind.VOICE_BIBLE,
            ArtifactKind.STORYBOARD_PLAN,
            ArtifactKind.RISK_REPORT,
            ArtifactKind.SELECTION_PLAN,
            ArtifactKind.COST_ESTIMATE,
            ArtifactKind.TRIAL_PLAN,
            ArtifactKind.TRIAL_REVIEW,
            ArtifactKind.QUALITY_REPORT,
            ArtifactKind.REPAIR_PLAN,
        ]
        start = order.index(target)
        return [current[kind.value] for kind in order[start:] if kind.value in current]

    @staticmethod
    def _rollback_status(target: ArtifactKind) -> WorkflowStatus:
        creative = {
            ArtifactKind.PREFERENCE_UNDERSTANDING,
            ArtifactKind.CONCEPT_SET,
            ArtifactKind.STORY_CORE,
            ArtifactKind.SEASON_PLAN,
            ArtifactKind.EPISODE_SCRIPT,
            ArtifactKind.STORY_REVIEW,
        }
        return (
            WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION
            if target in creative
            else WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION
        )

    @staticmethod
    def _assert_required_artifacts(
        workflow: DirectorWorkflowRun, approval_kind: ApprovalKind
    ) -> None:
        required: dict[ApprovalKind, set[ArtifactKind]] = {
            ApprovalKind.CREATIVE_PLAN: {
                ArtifactKind.STORY_CORE,
                ArtifactKind.EPISODE_SCRIPT,
                ArtifactKind.STORY_REVIEW,
            },
            ApprovalKind.SHOOTING_PLAN: {
                ArtifactKind.CHARACTER_BIBLE,
                ArtifactKind.VISUAL_BIBLE,
                ArtifactKind.VOICE_BIBLE,
                ArtifactKind.STORYBOARD_PLAN,
                ArtifactKind.RISK_REPORT,
                ArtifactKind.SELECTION_PLAN,
                ArtifactKind.COST_ESTIMATE,
            },
            ApprovalKind.TRIAL_BUDGET: {ArtifactKind.TRIAL_PLAN},
            ApprovalKind.PRODUCTION_BUDGET: {ArtifactKind.TRIAL_REVIEW},
            ApprovalKind.REPAIR_BUDGET: {ArtifactKind.REPAIR_PLAN},
        }
        missing = sorted(
            kind.value
            for kind in required.get(approval_kind, set())
            if kind.value not in workflow.current_artifact_versions
        )
        if missing:
            raise ValidationAppError(
                "required artifact versions are missing for approval",
                details={
                    "code": "APPROVAL_INPUTS_INCOMPLETE",
                    "approval_kind": approval_kind.value,
                    "missing_artifact_kinds": missing,
                },
            )

    @staticmethod
    def _assert_artifact_allowed(
        workflow: DirectorWorkflowRun, artifact_kind: ArtifactKind
    ) -> None:
        creative = {
            ArtifactKind.PREFERENCE_UNDERSTANDING,
            ArtifactKind.CONCEPT_SET,
            ArtifactKind.STORY_CORE,
            ArtifactKind.SEASON_PLAN,
            ArtifactKind.EPISODE_SCRIPT,
            ArtifactKind.STORY_REVIEW,
        }
        shooting = {
            ArtifactKind.CHARACTER_BIBLE,
            ArtifactKind.VISUAL_BIBLE,
            ArtifactKind.VOICE_BIBLE,
            ArtifactKind.STORYBOARD_PLAN,
            ArtifactKind.RISK_REPORT,
            ArtifactKind.SELECTION_PLAN,
            ArtifactKind.COST_ESTIMATE,
        }
        allowed: set[str]
        if artifact_kind in creative:
            allowed = {
                WorkflowStatus.DRAFTING_CREATIVE.value,
                WorkflowStatus.AWAITING_CREATIVE_CONFIRMATION.value,
            }
        elif artifact_kind in shooting:
            allowed = {
                WorkflowStatus.DRAFTING_SHOOTING_PLAN.value,
                WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION.value,
            }
        elif artifact_kind == ArtifactKind.TRIAL_PLAN:
            allowed = {
                WorkflowStatus.DRAFTING_SHOOTING_PLAN.value,
                WorkflowStatus.AWAITING_SHOOTING_CONFIRMATION.value,
                WorkflowStatus.AWAITING_TRIAL_AUTHORIZATION.value,
            }
        elif artifact_kind == ArtifactKind.TRIAL_REVIEW:
            allowed = {
                WorkflowStatus.TRIAL_RUNNING.value,
                WorkflowStatus.AWAITING_TRIAL_REVIEW.value,
                WorkflowStatus.FINAL_REVIEW.value,
            }
        elif artifact_kind == ArtifactKind.QUALITY_REPORT:
            allowed = {
                WorkflowStatus.TRIAL_RUNNING.value,
                WorkflowStatus.AWAITING_TRIAL_REVIEW.value,
                WorkflowStatus.PRODUCTION_RUNNING.value,
                WorkflowStatus.REPAIR_PROPOSED.value,
                WorkflowStatus.FINAL_REVIEW.value,
            }
        elif artifact_kind == ArtifactKind.REPAIR_PLAN:
            allowed = {
                WorkflowStatus.PRODUCTION_RUNNING.value,
                WorkflowStatus.REPAIR_PROPOSED.value,
            }
        elif artifact_kind == ArtifactKind.PRODUCTION_REVIEW:
            allowed = {WorkflowStatus.FINAL_REVIEW.value}
        else:
            allowed = set()
        if workflow.status not in allowed:
            raise ValidationAppError(
                "artifact kind is not writable in the current workflow state",
                details={
                    "code": "ARTIFACT_STAGE_NOT_ALLOWED",
                    "artifact_kind": artifact_kind.value,
                    "current_status": workflow.status,
                },
            )
