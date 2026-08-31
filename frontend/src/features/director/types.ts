export type DirectorStage = "creative" | "shooting" | "trial" | "production";

/** A non-persistent, single-shot design proposal returned by Director. */
export type ShotDirectorSuggestion = {
  base_shot_version: number;
  suggested_image_prompt: string;
  suggested_video_prompt: string;
  suggested_director_state: Record<string, unknown>;
  change_summary: string;
};

export type DirectorWorkflowStatus =
  | "drafting_creative"
  | "awaiting_creative_confirmation"
  | "drafting_shooting_plan"
  | "awaiting_shooting_confirmation"
  | "awaiting_trial_authorization"
  | "trial_running"
  | "awaiting_trial_review"
  | "awaiting_production_authorization"
  | "production_running"
  | "repair_proposed"
  | "awaiting_repair_authorization"
  | "assembling"
  | "final_review"
  | "completed"
  | "needs_human"
  | "blocked"
  | "cancelled";

export type DirectorArtifactKind =
  | "preference_understanding"
  | "concept_set"
  | "story_core"
  | "season_plan"
  | "episode_script"
  | "story_review"
  | "character_bible"
  | "visual_bible"
  | "voice_bible"
  | "storyboard_plan"
  | "risk_report"
  | "selection_plan"
  | "cost_estimate"
  | "trial_plan"
  | "trial_review"
  | "production_review"
  | "quality_report"
  | "repair_plan";

export type ApprovalKind =
  | "creative_plan"
  | "shooting_plan"
  | "trial_budget"
  | "production_budget"
  | "repair_budget"
  | "subjective_gate_override";

export type CreativeEntryMode = "no_idea" | "one_sentence" | "import_script";
export type CreationGoal = "self_expression" | "high_traffic" | "balanced";
export type AdaptationMode = "faithful" | "balanced" | "free";

export type DirectorWorkflow = {
  id: string;
  project_id: string;
  template_id: string;
  template_version: string;
  status: DirectorWorkflowStatus;
  current_stage: DirectorStage | "delivery";
  current_artifact_versions: Record<string, string>;
  version: number;
};

export type DirectorArtifactVersion<TPayload = Record<string, unknown>> = {
  id: string;
  project_id: string;
  workflow_run_id: string;
  artifact_kind: DirectorArtifactKind;
  revision_no: number;
  supersedes_version_id: string | null;
  source_kind: string;
  payload: TPayload;
  content_hash: string;
  status: string;
};

export type StoryConcept = {
  concept_id: string;
  title: string;
  logline: string;
  theme: string;
  character_relationship: string;
  core_conflict: string;
  ending_direction: string;
  why_it_fits: string;
};

export type ConceptSetPayload = {
  entry_mode: CreativeEntryMode;
  creation_goal: CreationGoal | null;
  adaptation_mode: AdaptationMode | null;
  source_rights_confirmed: boolean;
  preference_summary: string;
  concepts: StoryConcept[];
};

export type PreferenceUnderstandingPayload = {
  liked: string[];
  disliked: string[];
  inferred_preferences: string[];
  avoid: string[];
  interpretation_summary: string;
};

export type CharacterMotivation = {
  name: string;
  identity: string;
  desire: string;
  fear_or_cost: string;
};

export type StoryCorePayload = {
  selected_concept_id: string;
  theme: string;
  core_conflict: string;
  emotional_direction: string;
  ending: string;
  characters: CharacterMotivation[];
};

export type EpisodeScriptPayload = {
  title: string;
  target_duration_seconds: number;
  setup: string;
  turn: string;
  ending: string;
  dialogue: Array<{ speaker: string; text: string; emotion: string }>;
};

export type StoryReviewPayload = {
  status: "passed" | "needs_revision";
  logic_issues: string[];
  pacing_issues: string[];
  duration_risks: string[];
  closure_issues: string[];
  revision_suggestions: string[];
};

export type ApprovalRecord = {
  id: string;
  project_id: string;
  workflow_run_id: string;
  approval_kind: ApprovalKind;
  approved_artifact_versions: Record<string, string>;
  budget_authorization_id: string | null;
  reason: string | null;
  approved_at: string;
  invalidated_at: string | null;
};

export type BudgetAuthorization = {
  id: string;
  authorization_kind: ApprovalKind;
  pricing_snapshot_id: string;
  limit_amount: string;
  consumed_amount: string;
  currency: string;
  status: string;
  expires_at: string;
};

export type ChangeProposalResult = {
  proposal: {
    id: string;
    target_artifact_kind: DirectorArtifactKind;
    summary: string;
    replacement_payload: Record<string, unknown>;
    status: string;
  };
  impact: {
    id: string;
    invalidated_version_ids: string[];
    affected_shot_ids: string[];
    reusable_artifact_ids: string[];
    estimated_added_cost: string | null;
    estimated_added_time_seconds: number | null;
    details: Record<string, unknown>;
  };
};

export type DirectorWorkspaceSnapshot = {
  project_id: string;
  project_name: string;
  aspect_ratio: "9:16" | "16:9";
  workflow: DirectorWorkflow;
  current_artifacts: Partial<
    Record<DirectorArtifactKind, DirectorArtifactVersion<Record<string, unknown>>>
  >;
  approvals: ApprovalRecord[];
  /** @deprecated legacy quick-mode compatibility; professional API omits it. */
  budget_authorizations: BudgetAuthorization[];
  pending_changes: ChangeProposalResult[];
  issues: Array<{
    id: string;
    issue_type: string;
    source_stage: string;
    responsible_stage: string;
    severity: string;
    status: string;
    evidence: Array<Record<string, unknown>>;
    suggested_actions: string[];
    affected_version_refs: string[];
    resolution: Record<string, unknown>;
  }>;
  step_runs: Array<{
    id: string;
    step_key: string;
    skill_id: string;
    skill_version: string;
    execution_kind: string;
    status: string;
    input_version_refs: string[];
    output_version_refs: string[];
    error_code: string | null;
  }>;
  production_batches: Array<{
    id: string;
    batch_kind: string;
    status: string;
    budget_authorization_id: string;
    locked_version_refs: Record<string, string>;
    selected_shot_ids: string[];
    template_keys: string[];
    quality_policy_id: string;
    selection_snapshot: Record<string, unknown>;
    semantic_hash: string;
  }>;
  /** @deprecated legacy quick-mode compatibility; professional API omits it. */
  budget_reservations: Array<{
    id: string;
    batch_id: string;
    authorization_id: string;
    node_run_id: string | null;
    reserved_amount: string;
    actual_amount: string | null;
    currency: string;
    status: string;
  }>;
  latest_delivery: LatestDeliveryRead | null;
  allowed_actions: string[];
  next_action: string;
};

export type ConceptGenerateInput = {
  entry_mode: CreativeEntryMode;
  creation_goal?: CreationGoal | null;
  idea?: string;
  script_text?: string;
  adaptation_mode?: AdaptationMode | null;
  source_rights_confirmed?: boolean;
  confirmed_preference_version_id?: string | null;
  authorize_text_call: boolean;
  idempotency_key: string;
};

export type CreativePackageInput = {
  concept_version_id: string;
  selected_concept_id: string;
  theme: string;
  core_conflict: string;
  emotional_direction: string;
  ending: string;
  authorize_text_call: boolean;
  idempotency_key: string;
};

export type CreativePackageResult = {
  story_core: DirectorArtifactVersion<StoryCorePayload>;
  episode_script: DirectorArtifactVersion<EpisodeScriptPayload>;
  story_review: DirectorArtifactVersion<StoryReviewPayload>;
};

export type CharacterBiblePayload = {
  policy: "fictional_characters_only";
  real_person_reference_allowed: false;
  characters: Array<{
    character_id: string;
    name: string;
    age_range: string;
    facial_features: string;
    hair: string;
    body_shape: string;
    wardrobe: string;
    distinguishing_features: string[];
    locked_prompt: string;
    negative_prompt: string;
  }>;
};

export type VisualBiblePayload = {
  medium: "photorealistic_live_action";
  aspect_ratio: "9:16" | "16:9";
  era_and_setting: string;
  color_palette: string;
  lighting: string;
  lens_language: string;
  continuity_rules: string[];
  preview_is_generated_media: false;
};

export type VoiceBiblePayload = {
  language: "zh-CN";
  voice_clone_allowed: false;
  voices: Array<{
    character_id: string;
    character_name: string;
    voice_description: string;
    pace: "slow" | "medium" | "fast";
    emotional_range: string[];
    voice_clone: false;
  }>;
};

export type StoryboardShot = {
  shot_id: string;
  shot_number: number;
  duration_seconds: string;
  location: string;
  time_of_day: string;
  shot_type: "wide" | "medium" | "medium_close" | "close" | "over_shoulder" | "insert";
  camera_move: "static" | "push_in" | "pull_out" | "pan" | "tracking";
  characters: string[];
  action: string;
  dialogue: Array<{ speaker: string; text: string; emotion: string }>;
  image_prompt: string;
  video_prompt: string;
  transition: string;
};

export type StoryboardPlanPayload = {
  template_key: "live_action_dialogue_short_v1";
  aspect_ratio: "9:16" | "16:9";
  target_duration_seconds: number;
  shots: StoryboardShot[];
};

export type RiskReportPayload = {
  policy_id: "live-dialogue-preflight-v1";
  status: "ready" | "needs_revision" | "blocked";
  representative_shot_id: string;
  representative_shot_reason: string;
  risks: Array<{
    risk_id: string;
    shot_id: string | null;
    category:
      "identity" | "multi_person" | "motion" | "lip_sync" | "continuity" | "duration" | "model";
    severity: "info" | "warning" | "blocking";
    evidence: string;
    mitigation: string;
    requires_trial: boolean;
  }>;
};

export type SelectionPlanPayload = {
  policy_id: "director-model-selection-v1";
  status: "ready" | "configuration_required" | "unsupported";
  plans: Array<{
    purpose: "character_reference" | "keyframe" | "video" | "voice";
    provider_type: string | null;
    model_id: string | null;
    required_capabilities: string[];
    supported_capabilities: string[];
    evidence: Record<string, boolean>;
    pricing_snapshot: Record<string, unknown>;
    status: "ready" | "configuration_required" | "unsupported";
    blockers: string[];
  }>;
  fallback_allowed: false;
  advanced_parameters_hidden_in_quick_mode: true;
};

export type CostLine = {
  purpose: string;
  quantity: number;
  unit_amount: string | null;
  estimated_amount: string | null;
  currency: string;
  status: "known" | "provider_not_reported" | "configuration_required";
};

export type CostEstimatePayload = {
  pricing_snapshot_id: string;
  currency: string;
  trial: CostLine[];
  production: CostLine[];
  repair: CostLine[];
  trial_total: string | null;
  production_total: string | null;
  repair_total: string | null;
  requires_user_budget_limit: true;
  disclaimer: string;
};

export type TrialPlanPayload = {
  policy_id: "representative-shot-v1";
  representative_shot_id: string;
  selection_reason: string;
  planned_operations: string[];
  quality_dimensions: string[];
  budget_authorization_required: true;
};

export type QualityDimension =
  | "request_contract"
  | "identity"
  | "technical_integrity"
  | "voice_assignment"
  | "mouth_motion"
  | "continuity"
  | "narrative_and_performance";

export type QualityReportPayload = {
  policy_id: "live-dialogue-quality-v1";
  batch_id: string;
  logical_shot_id: string;
  overall_status: "passed" | "warning" | "needs_human" | "blocked";
  dimensions: Array<{
    dimension: QualityDimension;
    status: "passed" | "warning" | "needs_human" | "blocked" | "not_applicable";
    summary: string;
    evidence_refs: string[];
    signals: Record<string, unknown>;
  }>;
  hard_blockers: string[];
  limitations: string[];
  recommended_action: "accept" | "review" | "repair" | "stop";
};

export type ProductionQualityReportPayload = {
  policy_id: "live-dialogue-quality-v1";
  batch_id: string;
  shot_reports: QualityReportPayload[];
  overall_status: "passed" | "warning" | "needs_human" | "blocked";
  hard_blockers: string[];
};

export type TrialReviewPayload = {
  batch_id: string;
  quality_report_version_id: string;
  decision: "accept" | "repair" | "stop";
  accepted_quality: boolean;
  user_note: string;
  evidence_refs: string[];
};

export type ProductionReviewPayload = {
  batch_id: string;
  quality_report_version_id: string;
  decisions: Record<string, "accept" | "repair" | "stop">;
  user_note: string;
  accepted_shot_ids: string[];
  repair_shot_ids: string[];
};

export type ProductionExportRead = {
  export_id: string;
  export_status: string;
  mp4_object_key: string | null;
  mp4_hash: string | null;
  mp4_error: string | null;
  timeline_hash: string;
  srt_hash: string;
  package_hash: string;
  source_artifact_ids: string[];
  source_node_run_ids: string[];
  export_item_count: number;
};

export type LatestDeliveryRead = {
  export_id: string;
  status: string;
  items: Array<{
    kind: string;
    object_key: string;
    content_hash: string;
    byte_size: number;
  }>;
  program_mp4_error: string | null;
};

export type MaterializedNodeRun = {
  id: string;
  graph_version_id: string;
  graph_node_id: string;
  production_batch_id: string;
  budget_reservation_id: string;
  status: string;
  input_hash: string;
};

export type MaterializeBatchResult = {
  batch: DirectorWorkspaceSnapshot["production_batches"][number];
  node_runs: MaterializedNodeRun[];
};

export type RepairOptionContract = {
  repair_option_id: string;
  title: string;
  diagnosis: string;
  affected_shot_ids: string[];
  invalidated_node_keys: string[];
  reusable_artifact_ids: string[];
  changes: Array<{
    target: "prompt" | "reference" | "model" | "parameter" | "storyboard";
    summary: string;
    preview_before_ref: string | null;
    preview_after_ref: string | null;
  }>;
  estimated_cost: string | null;
  currency: string;
  estimated_time_seconds: number | null;
  residual_risks: string[];
};

export type RepairAuthorizeContract = {
  repair_option_id: string;
  budget_authorization_id: string;
  idempotency_key: string;
};

export type ShootingPackageResult = {
  character_bible: DirectorArtifactVersion<CharacterBiblePayload>;
  visual_bible: DirectorArtifactVersion<VisualBiblePayload>;
  voice_bible: DirectorArtifactVersion<VoiceBiblePayload>;
  storyboard_plan: DirectorArtifactVersion<StoryboardPlanPayload>;
  risk_report: DirectorArtifactVersion<RiskReportPayload>;
  selection_plan: DirectorArtifactVersion<SelectionPlanPayload>;
  cost_estimate: DirectorArtifactVersion<CostEstimatePayload>;
  trial_plan: DirectorArtifactVersion<TrialPlanPayload>;
};

export function shootingReadiness(snapshot: DirectorWorkspaceSnapshot): {
  ready: boolean;
  reasons: string[];
} {
  const storyboard = artifactPayload<StoryboardPlanPayload>(snapshot, "storyboard_plan");
  const risk = artifactPayload<RiskReportPayload>(snapshot, "risk_report");
  const selection = artifactPayload<SelectionPlanPayload>(snapshot, "selection_plan");
  const cost = artifactPayload<CostEstimatePayload>(snapshot, "cost_estimate");
  const reasons: string[] = [];
  if (!storyboard || storyboard.shots.length < 3 || storyboard.shots.length > 6) {
    reasons.push("分镜尚未形成可执行的 3–6 镜方案");
  }
  if (!risk || risk.status !== "ready") reasons.push("风险预审尚未达到可试拍状态");
  if (!selection || selection.status !== "ready")
    reasons.push("所需图片、视频或声音能力尚未配置并验证");
  if (!cost) {
    reasons.push("成本与价格快照尚未形成");
  } else if (cost.trial.some((line) => line.status !== "known") || cost.trial_total === null) {
    reasons.push("试拍价格尚未经过验证");
  }
  return { ready: reasons.length === 0, reasons };
}

export function artifactPayload<TPayload>(
  snapshot: DirectorWorkspaceSnapshot | undefined,
  kind: DirectorArtifactKind,
): TPayload | null {
  return (snapshot?.current_artifacts[kind]?.payload as TPayload | undefined) ?? null;
}
