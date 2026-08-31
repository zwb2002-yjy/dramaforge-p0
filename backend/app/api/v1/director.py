"""Controlled AI Director command endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.director.creative_service import DirectorCreativeService
from app.director.enums import ArtifactKind
from app.director.production_service import DirectorProductionService
from app.director.quality_service import DirectorQualityService
from app.director.repair_execution_service import DirectorRepairExecutionService
from app.director.repair_service import DirectorRepairService
from app.director.schemas import (
    ApprovalCreate,
    ApprovalRead,
    ApprovalResult,
    ArtifactVersionCreate,
    ArtifactVersionRead,
    BudgetAuthorizationCreate,
    BudgetAuthorizationRead,
    ChangeProposalCreate,
    ChangeProposalRead,
    ChangeProposalResult,
    ConceptGenerateRequest,
    CreativePackageGenerateRequest,
    CreativePackageResult,
    CreativeReviewGenerateRequest,
    DirectorWorkspaceSnapshot,
    ImpactReportRead,
    InspectProductionRequest,
    InspectTrialRequest,
    MaterializeBatchRequest,
    MaterializeBatchResult,
    MaterializedNodeRunRead,
    PreferenceInterpretRequest,
    ProductionBatchRead,
    ProductionExportRead,
    ProductionExportRequest,
    RepairAuthorizeRequest,
    RepairPlanRequest,
    RepairPlanResult,
    ResumePreSubmitRepairRequest,
    ReviewProductionRequest,
    ReviewTrialRequest,
    ShootingPackageGenerateRequest,
    ShootingPackageResult,
    StartWorkflowRequest,
    WorkflowRead,
)
from app.director.service import DirectorService
from app.director.shooting_service import DirectorShootingService
from app.director.snapshot_service import DirectorSnapshotService
from app.director.suggestion import (
    ShotDirectorSuggestion,
    ShotDirectorSuggestionRequest,
    ShotDirectorSuggestionService,
)
from app.shared.errors import ValidationAppError

router = APIRouter(tags=["director"], dependencies=[Depends(require_selected_workspace)])


@router.post(
    "/projects/{project_id}/director/budget-authorizations",
    response_model=BudgetAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def authorize_legacy_budget(
    project_id: UUID,
    body: BudgetAuthorizationCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> BudgetAuthorizationRead:
    """Historical quick-mode compatibility only.

    The professional workbench never calls this route. Provider pricing and
    settlement remain outside DramaForge; this route exists solely to replay
    already-versioned legacy workflows during migration.
    """
    authorization = await DirectorService(session).authorize_budget(
        project_id=project_id,
        actor=user,
        authorization_kind=body.authorization_kind,
        idempotency_key=body.idempotency_key,
        pricing_snapshot_id=body.pricing_snapshot_id,
        limit_amount=body.limit_amount,
        currency=body.currency,
        expires_at=body.expires_at,
    )
    return BudgetAuthorizationRead.model_validate(authorization)


@router.post(
    "/projects/{project_id}/director/workflow",
    response_model=WorkflowRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_workflow(
    project_id: UUID,
    body: StartWorkflowRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> WorkflowRead:
    workflow = await DirectorService(session).start_workflow(
        project_id=project_id,
        actor=user,
        template_id=body.template_id,
        template_version=body.template_version,
    )
    return WorkflowRead.model_validate(workflow)


@router.get(
    "/projects/{project_id}/director/workflow",
    response_model=WorkflowRead,
)
async def get_workflow(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> WorkflowRead:
    workflow = await DirectorService(session).get_workflow(project_id=project_id, actor=user)
    return WorkflowRead.model_validate(workflow)


@router.get(
    "/projects/{project_id}/director/workspace-snapshot",
    response_model=DirectorWorkspaceSnapshot,
)
async def get_director_workspace_snapshot(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> DirectorWorkspaceSnapshot:
    return await DirectorSnapshotService(session).get(project_id=project_id, actor=user)


@router.post(
    "/projects/{project_id}/director/shots/{shot_id}/suggestion",
    response_model=ShotDirectorSuggestion,
)
async def suggest_shot_design(
    project_id: UUID,
    shot_id: UUID,
    body: ShotDirectorSuggestionRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotDirectorSuggestion:
    """Return one read-only Director suggestion for the selected Shot.

    The service re-reads canonical Shot prompts/state and verifies the route
    Shot id, scene id, project and expected version.  This endpoint never
    persists the suggestion, starts an execution, or changes the Shot; the
    browser must apply the returned design to its draft and use the existing
    explicit Shot Design save command if the user wants to keep it.
    """
    if body.shot_id != shot_id:
        raise ValidationAppError(
            "shot id in the request body does not match the route",
            details={"code": "SHOT_SUGGESTION_SCOPE_MISMATCH"},
        )
    return await ShotDirectorSuggestionService(session).suggest(
        project_id=project_id,
        actor=user,
        request=body,
    )


@router.post(
    "/projects/{project_id}/director/artifact-versions",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def publish_artifact_version(
    project_id: UUID,
    body: ArtifactVersionCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    # Runtime evidence and repair decisions are service-owned facts.  Letting a
    # client publish them through the generic authoring endpoint would allow a
    # forged quality result to bypass the controlled trial/repair commands.
    if body.artifact_kind in {
        ArtifactKind.QUALITY_REPORT,
        ArtifactKind.TRIAL_REVIEW,
        ArtifactKind.PRODUCTION_REVIEW,
        ArtifactKind.REPAIR_PLAN,
    }:
        raise ValidationAppError(
            "this artifact kind can only be published by its Director command",
            details={
                "code": "DIRECTOR_SERVICE_COMMAND_REQUIRED",
                "artifact_kind": body.artifact_kind.value,
            },
        )
    version = await DirectorService(session).publish_artifact_version(
        project_id=project_id,
        actor=user,
        artifact_kind=body.artifact_kind,
        payload=dict(body.payload),
        source_kind=body.source_kind,
        source_run_id=None,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/approvals",
    response_model=ApprovalResult,
    status_code=status.HTTP_201_CREATED,
)
async def approve(
    project_id: UUID,
    body: ApprovalCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ApprovalResult:
    approval, workflow = await DirectorService(session).approve(
        project_id=project_id,
        actor=user,
        approval_kind=body.approval_kind,
        idempotency_key=body.idempotency_key,
        reason=body.reason,
        budget_authorization_id=body.budget_authorization_id,
    )
    return ApprovalResult(
        approval=ApprovalRead.model_validate(approval),
        workflow=WorkflowRead.model_validate(workflow),
    )


@router.post(
    "/projects/{project_id}/director/change-proposals",
    response_model=ChangeProposalResult,
    status_code=status.HTTP_201_CREATED,
)
async def propose_change(
    project_id: UUID,
    body: ChangeProposalCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ChangeProposalResult:
    proposal, impact = await DirectorService(session).propose_change(
        project_id=project_id,
        actor=user,
        idempotency_key=body.idempotency_key,
        target_artifact_kind=body.target_artifact_kind,
        summary=body.summary,
        replacement_payload=dict(body.replacement_payload),
    )
    return ChangeProposalResult(
        proposal=ChangeProposalRead.model_validate(proposal),
        impact=ImpactReportRead.model_validate(impact),
    )


@router.post(
    "/projects/{project_id}/director/change-proposals/{proposal_id}/confirm",
    response_model=ArtifactVersionRead,
)
async def apply_change(
    project_id: UUID,
    proposal_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorService(session).apply_change(
        project_id=project_id, proposal_id=proposal_id, actor=user
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/creative/concepts/generate",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_concepts(
    project_id: UUID,
    body: ConceptGenerateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorCreativeService(session).generate_concepts(
        project_id=project_id,
        actor=user,
        entry_mode=body.entry_mode,
        creation_goal=body.creation_goal,
        idea=body.idea,
        script_text=body.script_text,
        adaptation_mode=body.adaptation_mode,
        source_rights_confirmed=body.source_rights_confirmed,
        confirmed_preference_version_id=body.confirmed_preference_version_id,
        authorize_text_call=body.authorize_text_call,
        idempotency_key=body.idempotency_key,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/creative/preferences/interpret",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def interpret_preferences(
    project_id: UUID,
    body: PreferenceInterpretRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorCreativeService(session).interpret_preferences(
        project_id=project_id,
        actor=user,
        source_concept_version_id=body.source_concept_version_id,
        feedback=body.feedback,
        authorize_text_call=body.authorize_text_call,
        idempotency_key=body.idempotency_key,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/creative/package/generate",
    response_model=CreativePackageResult,
    status_code=status.HTTP_201_CREATED,
)
async def generate_creative_package(
    project_id: UUID,
    body: CreativePackageGenerateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> CreativePackageResult:
    story, script, review = await DirectorCreativeService(session).generate_creative_package(
        project_id=project_id,
        actor=user,
        concept_version_id=body.concept_version_id,
        selected_concept_id=body.selected_concept_id,
        theme=body.theme,
        core_conflict=body.core_conflict,
        emotional_direction=body.emotional_direction,
        ending=body.ending,
        authorize_text_call=body.authorize_text_call,
        idempotency_key=body.idempotency_key,
    )
    return CreativePackageResult(
        story_core=ArtifactVersionRead.model_validate(story),
        episode_script=ArtifactVersionRead.model_validate(script),
        story_review=ArtifactVersionRead.model_validate(review),
    )


@router.post(
    "/projects/{project_id}/director/creative/review/generate",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def regenerate_story_review(
    project_id: UUID,
    body: CreativeReviewGenerateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorCreativeService(session).regenerate_story_review(
        project_id=project_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/shooting/package/generate",
    response_model=ShootingPackageResult,
    status_code=status.HTTP_201_CREATED,
)
async def generate_shooting_package(
    project_id: UUID,
    body: ShootingPackageGenerateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShootingPackageResult:
    outputs = await DirectorShootingService(session).generate_shooting_package(
        project_id=project_id,
        actor=user,
        authorize_text_calls=body.authorize_text_calls,
        idempotency_key=body.idempotency_key,
    )
    return ShootingPackageResult(
        character_bible=ArtifactVersionRead.model_validate(outputs[0]),
        visual_bible=ArtifactVersionRead.model_validate(outputs[1]),
        voice_bible=ArtifactVersionRead.model_validate(outputs[2]),
        storyboard_plan=ArtifactVersionRead.model_validate(outputs[3]),
        risk_report=ArtifactVersionRead.model_validate(outputs[4]),
        selection_plan=ArtifactVersionRead.model_validate(outputs[5]),
        cost_estimate=ArtifactVersionRead.model_validate(outputs[6]),
        trial_plan=ArtifactVersionRead.model_validate(outputs[7]),
    )


@router.post(
    "/projects/{project_id}/director/trial/materialize",
    response_model=MaterializeBatchResult,
    status_code=status.HTTP_201_CREATED,
)
async def materialize_trial(
    project_id: UUID,
    body: MaterializeBatchRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> MaterializeBatchResult:
    batch, runs = await DirectorProductionService(session).materialize_trial(
        project_id=project_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return MaterializeBatchResult(
        batch=ProductionBatchRead.model_validate(batch),
        node_runs=[MaterializedNodeRunRead.model_validate(run) for run in runs],
    )


@router.post(
    "/projects/{project_id}/director/trial/inspect",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def inspect_trial(
    project_id: UUID,
    body: InspectTrialRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorQualityService(session).inspect_trial(
        project_id=project_id,
        batch_id=body.batch_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/trial/review",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def review_trial(
    project_id: UUID,
    body: ReviewTrialRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorQualityService(session).review_trial(
        project_id=project_id,
        batch_id=body.batch_id,
        decision=body.decision,
        user_note=body.user_note,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/production/materialize",
    response_model=MaterializeBatchResult,
    status_code=status.HTTP_201_CREATED,
)
async def materialize_production(
    project_id: UUID,
    body: MaterializeBatchRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> MaterializeBatchResult:
    batch, runs = await DirectorProductionService(session).materialize_production(
        project_id=project_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return MaterializeBatchResult(
        batch=ProductionBatchRead.model_validate(batch),
        node_runs=[MaterializedNodeRunRead.model_validate(run) for run in runs],
    )


@router.post(
    "/projects/{project_id}/director/production/inspect",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def inspect_production(
    project_id: UUID,
    body: InspectProductionRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorQualityService(session).inspect_production(
        project_id=project_id,
        batch_id=body.batch_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/production/review",
    response_model=ArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def review_production(
    project_id: UUID,
    body: ReviewProductionRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ArtifactVersionRead:
    version = await DirectorQualityService(session).review_production(
        project_id=project_id,
        batch_id=body.batch_id,
        decisions=body.decisions,
        user_note=body.user_note,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return ArtifactVersionRead.model_validate(version)


@router.post(
    "/projects/{project_id}/director/production/export",
    response_model=ProductionExportRead,
    status_code=status.HTTP_201_CREATED,
)
async def export_production(
    project_id: UUID,
    body: ProductionExportRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProductionExportRead:
    result = await DirectorProductionService(session).export_production(
        project_id=project_id,
        batch_id=body.batch_id,
        actor=user,
        try_ffmpeg=body.try_ffmpeg,
    )
    return ProductionExportRead(
        export_id=result.export_id,
        export_status=result.export_status,
        mp4_object_key=result.mp4_object_key,
        mp4_hash=result.mp4_hash,
        mp4_error=result.mp4_error,
        timeline_hash=result.timeline_hash,
        srt_hash=result.srt_hash,
        package_hash=result.package_hash,
        source_artifact_ids=result.source_artifact_ids,
        source_node_run_ids=result.source_node_run_ids,
        export_item_count=result.export_item_count,
    )


@router.post(
    "/projects/{project_id}/director/repairs/plan",
    response_model=RepairPlanResult,
    status_code=status.HTTP_201_CREATED,
)
async def plan_repairs(
    project_id: UUID,
    body: RepairPlanRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> RepairPlanResult:
    version = await DirectorRepairService(session).plan(
        project_id=project_id,
        batch_id=body.batch_id,
        quality_report_version_id=body.quality_report_version_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    raw_options = version.payload.get("options", [])
    options = raw_options if isinstance(raw_options, list) else []
    return RepairPlanResult(
        repair_plan_version=ArtifactVersionRead.model_validate(version),
        options=[dict(item) for item in options if isinstance(item, dict)],
    )


@router.post(
    "/projects/{project_id}/director/repairs/{repair_option_id}/authorize",
    response_model=MaterializeBatchResult,
    status_code=status.HTTP_201_CREATED,
)
async def authorize_repair(
    project_id: UUID,
    repair_option_id: str,
    body: RepairAuthorizeRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> MaterializeBatchResult:
    if body.repair_option_id != repair_option_id:
        raise ValidationAppError("repair option path and body differ")
    batch, runs = await DirectorRepairExecutionService(
        session
    ).authorize_and_materialize(
        project_id=project_id,
        repair_option_id=repair_option_id,
        budget_authorization_id=body.budget_authorization_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return MaterializeBatchResult(
        batch=ProductionBatchRead.model_validate(batch),
        node_runs=[MaterializedNodeRunRead.model_validate(run) for run in runs],
    )


@router.post(
    "/projects/{project_id}/director/repairs/batches/{batch_id}/resume-pre-submit",
    response_model=MaterializeBatchResult,
)
async def resume_pre_submit_repair(
    project_id: UUID,
    batch_id: UUID,
    body: ResumePreSubmitRepairRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> MaterializeBatchResult:
    batch, runs = await DirectorRepairExecutionService(
        session
    ).resume_pre_submit_failure(
        project_id=project_id,
        batch_id=batch_id,
        actor=user,
        idempotency_key=body.idempotency_key,
    )
    return MaterializeBatchResult(
        batch=ProductionBatchRead.model_validate(batch),
        node_runs=[MaterializedNodeRunRead.model_validate(run) for run in runs],
    )
