"""HTTP contracts for the Director workflow command API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.director.enums import ApprovalKind, ArtifactKind


class StartWorkflowRequest(BaseModel):
    template_id: str = "live_action_dialogue_short"
    template_version: str = "1.0.0"


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    template_id: str
    template_version: str
    status: str
    current_stage: str
    current_artifact_versions: dict[str, str]
    version: int


class ArtifactVersionCreate(BaseModel):
    artifact_kind: ArtifactKind
    payload: dict[str, Any] = Field(default_factory=dict)
    source_kind: str = Field(default="user", pattern="^(user|imported)$")


class ArtifactVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    artifact_kind: str
    revision_no: int
    supersedes_version_id: UUID | None
    source_kind: str
    payload: dict[str, Any]
    content_hash: str
    status: str


class BudgetAuthorizationCreate(BaseModel):
    authorization_kind: ApprovalKind
    idempotency_key: str = Field(min_length=1, max_length=160)
    pricing_snapshot_id: str = Field(min_length=1, max_length=160)
    limit_amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    expires_at: datetime


class BudgetAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    authorization_kind: str
    pricing_snapshot_id: str
    limit_amount: Decimal
    consumed_amount: Decimal
    currency: str
    status: str
    expires_at: datetime


class ApprovalCreate(BaseModel):
    approval_kind: ApprovalKind
    idempotency_key: str = Field(min_length=1, max_length=160)
    reason: str | None = Field(default=None, max_length=2000)
    budget_authorization_id: UUID | None = None


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    approval_kind: str
    approved_artifact_versions: dict[str, str]
    budget_authorization_id: UUID | None
    reason: str | None
    approved_at: datetime
    invalidated_at: datetime | None


class ApprovalResult(BaseModel):
    approval: ApprovalRead
    workflow: WorkflowRead


class ChangeProposalCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    target_artifact_kind: ArtifactKind
    summary: str = Field(min_length=1, max_length=4000)
    replacement_payload: dict[str, Any]


class ChangeProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    target_artifact_kind: str
    base_version_id: UUID | None
    summary: str
    replacement_payload: dict[str, Any]
    status: str


class ImpactReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    change_proposal_id: UUID
    invalidated_version_ids: list[str]
    affected_shot_ids: list[str]
    reusable_artifact_ids: list[str]
    estimated_added_cost: Decimal | None
    estimated_added_time_seconds: int | None
    details: dict[str, Any]


class ChangeProposalResult(BaseModel):
    proposal: ChangeProposalRead
    impact: ImpactReportRead


class ConceptGenerateRequest(BaseModel):
    entry_mode: str = Field(pattern="^(no_idea|one_sentence|import_script)$")
    creation_goal: str | None = Field(
        default=None, pattern="^(self_expression|high_traffic|balanced)$"
    )
    idea: str = Field(default="", max_length=4000)
    script_text: str = Field(default="", max_length=30000)
    adaptation_mode: str | None = Field(default=None, pattern="^(faithful|balanced|free)$")
    source_rights_confirmed: bool = False
    confirmed_preference_version_id: UUID | None = None
    authorize_text_call: bool = False
    idempotency_key: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> ConceptGenerateRequest:
        if self.entry_mode == "no_idea" and self.creation_goal is None:
            raise ValueError("creation_goal is required for no_idea entry")
        if self.entry_mode == "one_sentence" and not self.idea.strip():
            raise ValueError("idea is required for one_sentence entry")
        if self.entry_mode == "import_script":
            if not self.script_text.strip():
                raise ValueError("script_text is required for import_script entry")
            if not self.source_rights_confirmed:
                raise ValueError("source rights must be confirmed")
            if self.adaptation_mode is None:
                raise ValueError("adaptation_mode is required for import_script")
        return self


class PreferenceInterpretRequest(BaseModel):
    source_concept_version_id: UUID
    feedback: str = Field(min_length=1, max_length=4000)
    authorize_text_call: bool = False
    idempotency_key: str = Field(min_length=1, max_length=160)


class CreativePackageGenerateRequest(BaseModel):
    concept_version_id: UUID
    selected_concept_id: str = Field(min_length=1, max_length=40)
    theme: str = Field(min_length=1, max_length=200)
    core_conflict: str = Field(min_length=1, max_length=500)
    emotional_direction: str = Field(min_length=1, max_length=300)
    ending: str = Field(min_length=1, max_length=500)
    authorize_text_call: bool = False
    idempotency_key: str = Field(min_length=1, max_length=160)


class CreativePackageResult(BaseModel):
    story_core: ArtifactVersionRead
    episode_script: ArtifactVersionRead
    story_review: ArtifactVersionRead


class ShootingPackageGenerateRequest(BaseModel):
    authorize_text_calls: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class ShootingPackageResult(BaseModel):
    character_bible: ArtifactVersionRead
    visual_bible: ArtifactVersionRead
    voice_bible: ArtifactVersionRead
    storyboard_plan: ArtifactVersionRead
    risk_report: ArtifactVersionRead
    selection_plan: ArtifactVersionRead
    cost_estimate: ArtifactVersionRead
    trial_plan: ArtifactVersionRead


class WorkflowStepRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step_key: str
    skill_id: str
    skill_version: str
    execution_kind: str
    status: str
    input_version_refs: list[str]
    output_version_refs: list[str]
    error_code: str | None


class DirectorIssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    issue_type: str
    source_stage: str
    responsible_stage: str
    severity: str
    status: str
    evidence: list[dict[str, Any]]
    suggested_actions: list[str]
    affected_version_refs: list[str]
    resolution: dict[str, Any]


class ProductionBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_kind: str
    status: str
    budget_authorization_id: UUID
    locked_version_refs: dict[str, str]
    selected_shot_ids: list[str]
    template_keys: list[str]
    quality_policy_id: str
    selection_snapshot: dict[str, Any]
    semantic_hash: str


class BudgetReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    authorization_id: UUID
    node_run_id: UUID | None
    reserved_amount: Decimal
    actual_amount: Decimal | None
    currency: str
    status: str


class DeliveryItemRead(BaseModel):
    kind: str
    object_key: str
    content_hash: str
    byte_size: int


class LatestDeliveryRead(BaseModel):
    export_id: UUID
    status: str
    items: list[DeliveryItemRead]
    program_mp4_error: str | None


class DirectorWorkspaceSnapshot(BaseModel):
    project_id: UUID
    project_name: str
    aspect_ratio: str
    workflow: WorkflowRead
    current_artifacts: dict[str, ArtifactVersionRead]
    approvals: list[ApprovalRead]
    budget_authorizations: list[BudgetAuthorizationRead]
    pending_changes: list[ChangeProposalResult]
    issues: list[DirectorIssueRead]
    step_runs: list[WorkflowStepRunRead]
    production_batches: list[ProductionBatchRead]
    budget_reservations: list[BudgetReservationRead]
    latest_delivery: LatestDeliveryRead | None = None
    allowed_actions: list[str]
    next_action: str


class MaterializeBatchRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)


class MaterializedNodeRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    graph_version_id: UUID
    graph_node_id: UUID
    production_batch_id: UUID
    budget_reservation_id: UUID
    status: str
    input_hash: str


class MaterializeBatchResult(BaseModel):
    batch: ProductionBatchRead
    node_runs: list[MaterializedNodeRunRead]


class InspectTrialRequest(BaseModel):
    batch_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=160)


class ReviewTrialRequest(BaseModel):
    batch_id: UUID
    decision: Literal["accept", "repair", "stop"]
    user_note: str = Field(default="", max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=160)


class InspectProductionRequest(BaseModel):
    batch_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=160)


class ReviewProductionRequest(BaseModel):
    batch_id: UUID
    decisions: dict[str, Literal["accept", "repair", "stop"]] = Field(
        min_length=1, max_length=6
    )
    user_note: str = Field(default="", max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_shot_ids(self) -> ReviewProductionRequest:
        if any(
            not key.startswith("shot-")
            or not key[5:].isdigit()
            or int(key[5:]) not in range(1, 7)
            for key in self.decisions
        ):
            raise ValueError("production decisions require shot-1 through shot-6 keys")
        return self


class ProductionExportRequest(BaseModel):
    batch_id: UUID
    try_ffmpeg: bool = True


class ProductionExportRead(BaseModel):
    export_id: UUID
    export_status: str
    mp4_object_key: str | None
    mp4_hash: str | None
    mp4_error: str | None
    timeline_hash: str
    srt_hash: str
    package_hash: str
    source_artifact_ids: list[UUID]
    source_node_run_ids: list[UUID]
    export_item_count: int


class RepairPlanRequest(BaseModel):
    batch_id: UUID
    quality_report_version_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=160)


class RepairPlanResult(BaseModel):
    repair_plan_version: ArtifactVersionRead
    options: list[dict[str, Any]]


class RepairAuthorizeRequest(BaseModel):
    repair_option_id: str = Field(pattern=r"^repair-[a-f0-9]{12}$")
    budget_authorization_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=160)
