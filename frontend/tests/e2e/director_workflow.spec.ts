import { expect, test, type Page, type Route } from "@playwright/test";

const WORKSPACE_ID = "workspace-e2e";
const PROJECT_ID = "project-e2e";

type Status =
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
  | "final_review"
  | "assembling"
  | "completed";

type MockArtifact = {
  id: string;
  project_id: string;
  workflow_run_id: string;
  artifact_kind: string;
  revision_no: number;
  supersedes_version_id: string | null;
  source_kind: string;
  payload: Record<string, unknown>;
  content_hash: string;
  status: string;
};

type MockState = {
  status: Status;
  aspectRatio: "9:16" | "16:9";
  artifacts: Record<string, MockArtifact>;
  stepRuns: Array<Record<string, unknown>>;
  approvals: Array<Record<string, unknown>>;
  budgets: Array<Record<string, unknown>>;
  batches: Array<Record<string, unknown>>;
  runtimeRuns: Array<Record<string, unknown>>;
  latestDelivery: Record<string, unknown> | null;
  pendingChanges: Array<Record<string, unknown>>;
  reservations: Array<Record<string, unknown>>;
  mediaRequests: string[];
  requests: Array<{ method: string; path: string; body: Record<string, unknown> }>;
  createdAspects: string[];
};

const concepts = [
  { concept_id: "concept-1", title: "雨夜来电", logline: "搬家前夜，她接到失踪姐姐的电话。", theme: "告别与相信", character_relationship: "疏离姐妹", core_conflict: "她必须在离开和追寻真相之间选择", ending_direction: "她留下并找到线索", why_it_fits: "单场景对白可在短时长闭环" },
  { concept_id: "concept-2", title: "最后一碗面", logline: "关店前，父亲终于承认一直在等女儿回家。", theme: "和解", character_relationship: "父女", core_conflict: "骄傲阻止两人说出真心", ending_direction: "共同保留老店招牌", why_it_fits: "情绪克制、表演集中" },
  { concept_id: "concept-3", title: "电梯第十层", logline: "两个陌生人发现自己都在逃避同一场婚礼。", theme: "选择", character_relationship: "陌生人", core_conflict: "电梯恢复前必须决定是否回去", ending_direction: "两人分别面对真实选择", why_it_fits: "空间集中、冲突明确" },
];

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function artifact(kind: string, payload: Record<string, unknown>, revision = 1): MockArtifact {
  return {
    id: `${kind}-v${revision}`,
    project_id: PROJECT_ID,
    workflow_run_id: "workflow-e2e",
    artifact_kind: kind,
    revision_no: revision,
    supersedes_version_id: revision > 1 ? `${kind}-v${revision - 1}` : null,
    source_kind: "service",
    payload,
    content_hash: `${kind}-hash-${revision}`,
    status: "draft",
  };
}

function qualityReport(batchId: string) {
  const names = ["request_contract", "identity", "technical_integrity", "voice_assignment", "mouth_motion", "continuity", "narrative_and_performance"];
  return {
    policy_id: "live-dialogue-quality-v1",
    batch_id: batchId,
    shot_reports: [{
      policy_id: "live-dialogue-quality-v1",
      batch_id: batchId,
      logical_shot_id: "shot-1",
      overall_status: "warning",
      dimensions: names.map((dimension) => ({ dimension, status: dimension === "identity" ? "warning" : "passed", summary: dimension === "identity" ? "人物外观有轻微漂移，请创作者判断。" : "证据通过。", evidence_refs: [`run:${dimension}`], signals: {} })),
      hard_blockers: [],
      limitations: ["自动指标不能替代人物整体观感。"],
      recommended_action: "review",
    }],
    overall_status: "warning",
    hard_blockers: [],
  };
}

function baseCreativeArtifacts(aspectRatio: "9:16" | "16:9") {
  const cost = {
    pricing_snapshot_id: "prices-e2e",
    currency: "CNY",
    trial: [{ purpose: "video", quantity: 1, unit_amount: "1.00", estimated_amount: "1.00", currency: "CNY", status: "known" }],
    production: [{ purpose: "video", quantity: 3, unit_amount: "1.00", estimated_amount: "3.00", currency: "CNY", status: "known" }],
    repair: [{ purpose: "video", quantity: 1, unit_amount: "1.50", estimated_amount: "1.50", currency: "CNY", status: "known" }],
    trial_total: "1.00",
    production_total: "3.00",
    repair_total: "1.50",
    requires_user_budget_limit: true,
    disclaimer: "以已验证价格快照为预算上限依据。",
  };
  return {
    story_core: artifact("story_core", { selected_concept_id: "concept-1", theme: "告别与相信", core_conflict: "她必须选择离开还是寻找姐姐", emotional_direction: "戒备 → 动摇 → 坚定", ending: "她留下并找到第一条线索", characters: [{ name: "林夏", identity: "记者", desire: "找到姐姐", fear_or_cost: "错过离开的机会" }] }),
    episode_script: artifact("episode_script", { title: "雨夜来电", target_duration_seconds: 24, setup: "林夏准备离开", turn: "旧手机响起", ending: "她转身冲进雨里", dialogue: [{ speaker: "林夏", text: "姐，是你吗？", emotion: "震惊" }] }),
    story_review: artifact("story_review", { status: "passed", logic_issues: [], pacing_issues: [], duration_risks: [], closure_issues: [], revision_suggestions: [] }),
    character_bible: artifact("character_bible", { policy: "fictional_characters_only", real_person_reference_allowed: false, characters: [{ character_id: "lin-xia", name: "林夏", age_range: "25-30", facial_features: "清晰眉眼与窄下颌", hair: "黑色短发", body_shape: "纤细", wardrobe: "深色风衣", distinguishing_features: ["左眉小痣"], locked_prompt: "fictional Lin Xia", negative_prompt: "identity drift" }] }),
    visual_bible: artifact("visual_bible", { medium: "photorealistic_live_action", aspect_ratio: aspectRatio, era_and_setting: "现代雨夜公寓", color_palette: "冷青与暖黄", lighting: "窗外冷光", lens_language: "克制近景", continuity_rules: ["风衣与短发保持一致"], preview_is_generated_media: false }),
    voice_bible: artifact("voice_bible", { language: "zh-CN", voice_clone_allowed: false, voices: [{ character_id: "lin-xia", character_name: "林夏", voice_description: "年轻、克制", pace: "medium", emotional_range: ["戒备", "震惊"], voice_clone: false }] }),
    storyboard_plan: artifact("storyboard_plan", { template_key: "live_action_dialogue_short_v1", aspect_ratio: aspectRatio, target_duration_seconds: 24, shots: [1, 2, 3].map((number) => ({ shot_id: `shot-${number}`, shot_number: number, duration_seconds: "8", location: "公寓", time_of_day: "夜", shot_type: number === 1 ? "medium" : "close", camera_move: "static", characters: ["林夏"], action: `动作 ${number}`, dialogue: number === 2 ? [{ speaker: "林夏", text: "姐，是你吗？", emotion: "震惊" }] : [], image_prompt: `frame ${number}`, video_prompt: `video ${number}`, transition: "cut" })) }),
    risk_report: artifact("risk_report", { policy_id: "live-dialogue-preflight-v1", status: "ready", representative_shot_id: "shot-1", representative_shot_reason: "正面对白最能暴露身份和口型风险", risks: [{ risk_id: "risk-1", shot_id: "shot-1", category: "identity", severity: "warning", evidence: "角色正面近景", mitigation: "先试拍并注入角色锚点", requires_trial: true }] }),
    selection_plan: artifact("selection_plan", { policy_id: "director-model-selection-v1", status: "ready", plans: ["character_reference", "keyframe", "video", "voice"].map((purpose) => ({ purpose, provider_type: "agnes", model_id: `${purpose}-model`, required_capabilities: [], supported_capabilities: [], evidence: {}, pricing_snapshot: {}, status: "ready", blockers: [] })), fallback_allowed: false, advanced_parameters_hidden_in_quick_mode: true }),
    cost_estimate: artifact("cost_estimate", cost),
    trial_plan: artifact("trial_plan", { policy_id: "representative-shot-v1", representative_shot_id: "shot-1", selection_reason: "正面对白最能暴露身份和口型风险", planned_operations: ["keyframe", "video", "voice"], quality_dimensions: ["identity", "mouth_motion"], budget_authorization_required: true }),
  };
}

function newState(): MockState {
  return { status: "drafting_creative", aspectRatio: "9:16", artifacts: {}, stepRuns: [], approvals: [], budgets: [], batches: [], runtimeRuns: [], latestDelivery: null, pendingChanges: [], reservations: [], mediaRequests: [], requests: [], createdAspects: [] };
}

function allowedActions(status: Status) {
  const byStatus: Partial<Record<Status, string[]>> = {
    drafting_creative: ["generate_concepts", "import_script"],
    awaiting_creative_confirmation: ["propose_change", "confirm_creative_plan"],
    drafting_shooting_plan: ["propose_change", "generate_shooting_package"],
    awaiting_shooting_confirmation: ["confirm_shooting_plan"],
    awaiting_trial_authorization: ["authorize_trial_budget"],
    trial_running: ["view_trial_progress"],
    awaiting_trial_review: ["review_trial"],
    awaiting_production_authorization: ["propose_change", "authorize_production_budget"],
    production_running: ["view_production_progress"],
    final_review: ["propose_change", "review_evidence"],
    repair_proposed: ["propose_change", "select_repair_option"],
    awaiting_repair_authorization: ["propose_change", "authorize_repair_budget"],
    assembling: ["view_assembly_progress"],
    completed: ["propose_change", "download_delivery"],
  };
  return byStatus[status] ?? [];
}

function workspaceSnapshot(state: MockState) {
  return {
    project_id: PROJECT_ID,
    project_name: "雨夜来电",
    aspect_ratio: state.aspectRatio,
    workflow: { id: "workflow-e2e", project_id: PROJECT_ID, template_id: "live_action_dialogue_short", template_version: "1.0.0", status: state.status, current_stage: state.status === "drafting_creative" || state.status === "awaiting_creative_confirmation" ? "creative" : state.status.includes("shooting") ? "shooting" : state.status.includes("trial") ? "trial" : "production", current_artifact_versions: Object.fromEntries(Object.entries(state.artifacts).map(([key, value]) => [key, value.id])), version: 10 },
    current_artifacts: state.artifacts,
    approvals: state.approvals,
    budget_authorizations: state.budgets,
    pending_changes: state.pendingChanges,
    issues: [],
    step_runs: state.stepRuns,
    production_batches: state.batches,
    budget_reservations: state.reservations,
    latest_delivery: state.latestDelivery,
    allowed_actions: state.pendingChanges.length > 0 ? ["confirm_change"] : allowedActions(state.status),
    next_action: "mock next action",
  };
}

function runtimeSnapshot(state: MockState) {
  return { project_id: PROJECT_ID, name: "雨夜来电", node_runs: state.runtimeRuns, artifacts: [] };
}

function batch(kind: "trial" | "production" | "repair", id: string) {
  return { id, batch_kind: kind, status: "running", budget_authorization_id: `budget-${kind}`, locked_version_refs: {}, selected_shot_ids: ["shot-1"], template_keys: ["dialogue_post_dub_shot_v1"], quality_policy_id: "live-dialogue-quality-v1", selection_snapshot: kind === "repair" ? { root_source_batch_id: "production-batch" } : {}, semantic_hash: `${kind}-hash` };
}

function completedRun(batchId: string) {
  return { id: `run-${batchId}`, status: "completed", result_artifact_id: null, output_summary: {}, input_snapshot: { production_batch_id: batchId, logical_shot_id: "shot-1" }, idempotency_key: `run-${batchId}`, attempt_no: 1, node_key: "composite", provider_cost: "1.00", started_at: new Date().toISOString(), finished_at: new Date().toISOString(), error_code: null, error_summary: null, upstream_dependencies: [] };
}

function seedProduction(state: MockState) {
  state.artifacts = { ...baseCreativeArtifacts(state.aspectRatio), trial_review: artifact("trial_review", { batch_id: "trial-batch", quality_report_version_id: "trial-quality", decision: "accept", accepted_quality: true, user_note: "试拍可接受", evidence_refs: [] }) };
  state.status = "awaiting_production_authorization";
  state.batches = [{ ...batch("trial", "trial-batch"), status: "accepted" }];
}

async function installDirectorMock(page: Page, initial?: (state: MockState) => void) {
  const state = newState();
  initial?.(state);
  await page.route("**/health", (route) => json(route, { status: "ok", service: "dramaforge-api", version: "e2e", env: "test", db: "up" }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
    state.requests.push({ method, path, body });

    if (method === "GET" && path === "/api/v1/auth/bootstrap-status") return json(route, { owner_initialized: true, registration_available: false, public_registration_enabled: false });
    if (method === "GET" && path === "/api/v1/auth/me") return json(route, { id: "user-e2e", email: "creator@example.com", display_name: "创作者" });
    if (method === "GET" && path === "/api/v1/auth/csrf") return json(route, { csrf_token: "csrf-e2e" });
    if (method === "GET" && path === "/api/v1/workspaces") return json(route, [{ id: WORKSPACE_ID, owner_user_id: "user-e2e", name: "个人空间" }]);
    if (method === "GET" && path === `/api/v1/workspaces/${WORKSPACE_ID}/projects`) return json(route, []);
    if (method === "GET" && path === `/api/v1/workspaces/${WORKSPACE_ID}/provider-connections`) return json(route, []);
    if (method === "GET" && path === `/api/v1/workspaces/${WORKSPACE_ID}/model-profiles`) return json(route, []);
    if (method === "GET" && path === "/api/v1/model-slots") return json(route, []);
    if (method === "GET" && path === "/api/v1/provider-plugins") return json(route, []);
    if (method === "POST" && path === "/api/v1/creation/start-project") {
      state.aspectRatio = body.aspect_ratio as "9:16" | "16:9";
      state.createdAspects.push(state.aspectRatio);
      return json(route, { project_id: PROJECT_ID, experience_mode: "quick", text_provider_operations: 0 });
    }
    if (method === "GET" && path === `/api/v1/projects/${PROJECT_ID}/snapshot`) return json(route, runtimeSnapshot(state));
    if (method === "GET" && path === `/api/v1/projects/${PROJECT_ID}/shots`) return json(route, []);
    if (method === "GET" && path === `/api/v1/projects/${PROJECT_ID}/director/workspace-snapshot`) return json(route, workspaceSnapshot(state));

    if (method === "POST" && path.endsWith("/creative/concepts/generate")) {
      const revision = state.artifacts.concept_set ? 2 : 1;
      const previous = state.artifacts.concept_set;
      state.artifacts.concept_set = artifact("concept_set", { entry_mode: body.entry_mode, creation_goal: body.creation_goal ?? null, adaptation_mode: body.adaptation_mode ?? null, source_rights_confirmed: Boolean(body.source_rights_confirmed), preference_summary: "", concepts }, revision);
      if (previous) state.artifacts.concept_set.supersedes_version_id = previous.id;
      return json(route, state.artifacts.concept_set, 201);
    }
    if (method === "POST" && path.endsWith("/creative/preferences/interpret")) {
      const source = String(body.source_concept_version_id);
      state.artifacts.preference_understanding = artifact("preference_understanding", { liked: ["克制的人物关系"], disliked: ["悲剧结局"], inferred_preferences: ["生活流冲突"], avoid: ["反转堆砌"], interpretation_summary: "你喜欢克制关系，但希望结局保留希望。" });
      state.stepRuns.push({ id: "preference-run", step_key: "interpret_preferences", skill_id: "preference", skill_version: "1", execution_kind: "agent_run", status: "succeeded", input_version_refs: [source], output_version_refs: [state.artifacts.preference_understanding.id], error_code: null });
      return json(route, state.artifacts.preference_understanding, 201);
    }
    if (method === "POST" && path.endsWith("/creative/package/generate")) {
      const seeded = baseCreativeArtifacts(state.aspectRatio);
      state.artifacts.story_core = seeded.story_core;
      state.artifacts.episode_script = seeded.episode_script;
      state.artifacts.story_review = seeded.story_review;
      state.status = "awaiting_creative_confirmation";
      return json(route, { story_core: seeded.story_core, episode_script: seeded.episode_script, story_review: seeded.story_review }, 201);
    }
    if (method === "POST" && /\/change-proposals\/[^/]+\/confirm$/.test(path)) {
      const pending = state.pendingChanges[0];
      const proposal = pending?.proposal as Record<string, unknown> | undefined;
      if (!proposal) return json(route, { detail: "No pending change" }, 409);
      const previous = state.artifacts.story_core;
      state.artifacts.story_core = artifact("story_core", proposal.replacement_payload as Record<string, unknown>, (previous?.revision_no ?? 1) + 1);
      state.artifacts.story_core.supersedes_version_id = previous?.id ?? null;
      delete state.artifacts.episode_script;
      delete state.artifacts.story_review;
      state.batches = state.batches.map((batch) => ({ ...batch, status: "superseded_by_change" }));
      state.reservations = state.reservations.map((reservation) => ({ ...reservation, status: "released" }));
      state.pendingChanges = [];
      state.status = "awaiting_creative_confirmation";
      return json(route, state.artifacts.story_core);
    }
    if (method === "POST" && path.endsWith("/change-proposals")) {
      const original = state.artifacts.story_core;
      if (!original) return json(route, { detail: "No current story core" }, 422);
      const proposal = {
        id: "change-story-core-1",
        target_artifact_kind: "story_core",
        summary: body.summary,
        replacement_payload: body.replacement_payload,
        status: "awaiting_confirmation",
      };
      const impact = {
        id: "impact-story-core-1",
        invalidated_version_ids: [original.id, state.artifacts.episode_script?.id, state.artifacts.story_review?.id].filter(Boolean),
        affected_shot_ids: state.batches.flatMap((batch) => (batch.selected_shot_ids as string[]) ?? []),
        reusable_artifact_ids: [],
        estimated_added_cost: null,
        estimated_added_time_seconds: null,
        details: {
          requires_confirmation: true,
          affected_batch_ids: state.batches.map((batch) => batch.id),
          releasable_reservation_ids: state.reservations.filter((reservation) => reservation.status === "reserved").map((reservation) => reservation.id),
          historical_settled_amount: "0",
          historical_currencies: ["CNY"],
          media_reuse_policy: state.batches.length ? "none_until_regenerated_and_reapproved" : "not_applicable",
        },
      };
      state.pendingChanges = [{ proposal, impact }];
      return json(route, { proposal, impact }, 201);
    }
    if (method === "POST" && path.endsWith("/shooting/package/generate")) {
      state.artifacts = { ...state.artifacts, ...baseCreativeArtifacts(state.aspectRatio) };
      state.status = "awaiting_shooting_confirmation";
      return json(route, state.artifacts, 201);
    }
    if (method === "POST" && path.endsWith("/budget-authorizations")) {
      const authorization = { id: `budget-${state.budgets.length + 1}`, authorization_kind: body.authorization_kind, pricing_snapshot_id: body.pricing_snapshot_id, limit_amount: body.limit_amount, consumed_amount: "0", currency: body.currency, status: "active", expires_at: body.expires_at };
      state.budgets.push(authorization);
      return json(route, authorization, 201);
    }
    if (method === "POST" && path.endsWith("/approvals")) {
      const kind = String(body.approval_kind);
      state.approvals.push({ id: `approval-${kind}`, approval_kind: kind, approved_artifact_versions: {}, budget_authorization_id: body.budget_authorization_id ?? null, reason: null, approved_at: new Date().toISOString(), invalidated_at: null });
      if (kind === "creative_plan") state.status = "drafting_shooting_plan";
      if (kind === "shooting_plan") state.status = "awaiting_trial_authorization";
      if (kind === "trial_budget") state.status = "trial_running";
      if (kind === "production_budget") state.status = "production_running";
      return json(route, { approval: state.approvals.at(-1), workflow: workspaceSnapshot(state).workflow }, 201);
    }
    if (method === "POST" && path.endsWith("/trial/materialize")) {
      state.mediaRequests.push(path);
      const value = batch("trial", "trial-batch");
      state.batches.push(value);
      state.runtimeRuns = [completedRun("trial-batch")];
      return json(route, { batch: value, node_runs: state.runtimeRuns }, 201);
    }
    if (method === "POST" && path.endsWith("/trial/inspect")) {
      const value = qualityReport("trial-batch").shot_reports[0];
      state.artifacts.quality_report = artifact("quality_report", value);
      state.status = "awaiting_trial_review";
      return json(route, state.artifacts.quality_report, 201);
    }
    if (method === "POST" && path.endsWith("/trial/review")) {
      state.artifacts.trial_review = artifact("trial_review", { batch_id: "trial-batch", quality_report_version_id: state.artifacts.quality_report?.id ?? "quality", decision: body.decision, accepted_quality: body.decision === "accept", user_note: body.user_note, evidence_refs: [] });
      state.status = body.decision === "accept" ? "awaiting_production_authorization" : "repair_proposed";
      return json(route, state.artifacts.trial_review, 201);
    }
    if (method === "POST" && path.endsWith("/production/materialize")) {
      state.mediaRequests.push(path);
      const value = batch("production", "production-batch");
      state.batches.push(value);
      state.runtimeRuns = [completedRun("production-batch")];
      return json(route, { batch: value, node_runs: state.runtimeRuns }, 201);
    }
    if (method === "POST" && path.endsWith("/production/inspect")) {
      const batchId = String(body.batch_id);
      state.artifacts.quality_report = artifact("quality_report", qualityReport(batchId));
      state.status = "final_review";
      return json(route, state.artifacts.quality_report, 201);
    }
    if (method === "POST" && path.endsWith("/production/review")) {
      const batchId = String(body.batch_id);
      const decisions = body.decisions as Record<string, string>;
      state.artifacts.production_review = artifact("production_review", { batch_id: batchId, quality_report_version_id: state.artifacts.quality_report.id, decisions, user_note: body.user_note, accepted_shot_ids: Object.keys(decisions).filter((id) => decisions[id] === "accept"), repair_shot_ids: Object.keys(decisions).filter((id) => decisions[id] === "repair") });
      state.status = Object.values(decisions).includes("repair") ? "repair_proposed" : "assembling";
      return json(route, state.artifacts.production_review, 201);
    }
    if (method === "POST" && path.endsWith("/repairs/plan")) {
      const plan = { batch_id: body.batch_id, quality_report_version_id: body.quality_report_version_id, additional_budget_required: true, options: [{ repair_option_id: "repair-0123456789ab", title: "强化角色锚点", diagnosis: "人物身份有轻微漂移", affected_shot_ids: ["shot-1"], invalidated_node_keys: ["keyframe", "video", "composite"], reusable_artifact_ids: ["voice-artifact"], changes: [{ target: "reference", summary: "重新注入已锁定角色参考图", preview_before_ref: null, preview_after_ref: null }], estimated_cost: "1.50", currency: "CNY", estimated_time_seconds: 90, residual_risks: ["主观表演仍需再次验收"] }] };
      state.artifacts.repair_plan = artifact("repair_plan", plan);
      state.status = "awaiting_repair_authorization";
      return json(route, { repair_plan_version: state.artifacts.repair_plan, options: plan.options }, 201);
    }
    if (method === "POST" && /\/repairs\/repair-[^/]+\/authorize$/.test(path)) {
      state.mediaRequests.push(path);
      const value = batch("repair", "repair-batch");
      state.batches.push(value);
      state.runtimeRuns = [completedRun("repair-batch")];
      state.status = "production_running";
      return json(route, { batch: value, node_runs: state.runtimeRuns }, 201);
    }
    if (method === "POST" && path.endsWith("/production/export")) {
      state.status = "completed";
      state.latestDelivery = { export_id: "export-e2e", status: "completed", items: [{ kind: "accepted_composite", object_key: "exports/video.mp4", content_hash: "video", byte_size: 100 }, { kind: "package", object_key: "exports/package.zip", content_hash: "zip", byte_size: 200 }, { kind: "program_mp4", object_key: "exports/program.mp4", content_hash: "mp4", byte_size: 300 }], program_mp4_error: null };
      return json(route, { export_id: "export-e2e", export_status: "completed", mp4_object_key: "exports/program.mp4", mp4_hash: "mp4", mp4_error: null, timeline_hash: "timeline", srt_hash: "srt", package_hash: "zip", source_artifact_ids: [], source_node_run_ids: [], export_item_count: 1 }, 201);
    }
    if (method === "POST" && path.includes("/exports/export-e2e/download-grant")) return json(route, { export_id: "export-e2e", object_key: `exports/${url.searchParams.get("object_role")}`, token: `token-${url.searchParams.get("object_role")}`, expires_at: Date.now() + 60_000 });
    if (method === "GET" && path.includes("/exports/export-e2e/download")) return route.fulfill({ status: 200, contentType: "application/octet-stream", body: "mock export" });
    return json(route, { detail: `Unhandled mock route: ${method} ${path}` }, 500);
  });
  return state;
}

async function expectCleanRuntime(page: Page, run: () => Promise<void>) {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await run();
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
}

test("Director creation supports all three entries and restores confirmed preference understanding", async ({ page }) => {
  const state = await installDirectorMock(page);
  await expectCleanRuntime(page, async () => {
    await page.goto(`/projects/${PROJECT_ID}/quick`);
    await expect(page.getByTestId("quick-creation-workspace")).toBeVisible();
    await expect(page.getByRole("link", { name: "专业生产" })).toHaveAttribute(
      "href",
      `/projects/${PROJECT_ID}/production`,
    );
    await expect(page.getByTestId("workstation-shell")).toHaveCount(0);
    await expect(page.getByTestId("director-stage-rail").locator("li")).toHaveCount(4);
    await expect(page.getByRole("radio", { name: /我还没有想法/ })).toBeChecked();
    await expect(page.getByText("平台热点和高流量题材")).toBeVisible();

    await page.getByRole("radio", { name: /我有自己的剧本/ }).click();
    await expect(page.getByLabel("粘贴剧本文字")).toBeVisible();
    await expect(page.getByLabel(/我确认自己拥有/)).not.toBeChecked();

    await page.getByRole("radio", { name: /我有一句话创意/ }).click();
    await page.getByLabel("用一句话说出你最想看到的故事").fill("搬家前夜，她接到失踪姐姐的电话。");
    await page.getByTestId("generate-concepts").click();
    await expect(page.getByTestId("concept-set").locator("[data-testid^='concept-']")).toHaveCount(3);
    expect(state.requests.some((request) => request.path.endsWith("/creative/concepts/generate"))).toBe(true);
    expect(state.mediaRequests).toEqual([]);

    await page.getByLabel("还没选中？直接说喜欢和不喜欢的部分").fill("喜欢克制的姐妹关系，但不要悲剧和堆反转。");
    await page.getByRole("button", { name: "生成偏好理解卡" }).click();
    await expect(page.getByTestId("preference-understanding-card")).toContainText("结局保留希望");

    await page.reload();
    await expect(page.getByTestId("preference-understanding-card")).toBeVisible();
    await page.getByRole("button", { name: "理解正确，按这张卡生成下一版" }).click();
    await expect(page.getByTestId("concept-set")).toContainText("第 2 版");
    await expect(page.getByTestId("preference-understanding-card")).toHaveCount(0);

    await page.getByTestId("concept-concept-1").click();
    await page.getByLabel("情绪走向").fill("戒备 → 动摇 → 坚定");
    await page.getByTestId("generate-creative-package").click();
    await expect(page.getByTestId("creative-package-review")).toContainText("剧本预审通过");
    await page.getByRole("button", { name: "确认创作方案，进入拍摄方案" }).click();
    await expect(page.getByTestId("shooting-stage")).toBeVisible();

    await page.getByRole("button", { name: "授权本次文字生成并准备拍摄方案" }).click();
    await expect(page.getByTestId("shooting-storyboard").locator("article")).toHaveCount(3);
    await page.getByRole("button", { name: "确认拍摄方案" }).click();
    await expect(page.getByTestId("trial-budget-panel")).toBeVisible();
    expect(state.mediaRequests).toEqual([]);

    await page.getByLabel(/我已看过代表镜头/).check();
    await page.getByRole("button", { name: "确认并授权试拍预算" }).click();
    await expect(page.getByRole("button", { name: "开始代表镜头试拍" })).toBeVisible();
    expect(state.mediaRequests).toEqual([]);
    await page.reload();
    await expect(page.getByRole("button", { name: "开始代表镜头试拍" })).toBeVisible();
    expect(state.mediaRequests).toEqual([]);
  });
});

test("locked creative changes show an impact preview before confirmation and update both workspaces", async ({ page }) => {
  const state = await installDirectorMock(page, (value) => {
    const seeded = baseCreativeArtifacts(value.aspectRatio);
    value.artifacts = {
      story_core: seeded.story_core,
      episode_script: seeded.episode_script,
      story_review: seeded.story_review,
    };
    value.status = "awaiting_creative_confirmation";
  });
  await expectCleanRuntime(page, async () => {
    await page.goto(`/projects/${PROJECT_ID}/quick`);
    await expect(page.getByTestId("locked-creative-change")).toBeVisible();
    await page.getByLabel("结局落点").last().fill("她没有离开，而是留下来面对真相。");
    await page.getByTestId("propose-locked-creative-change").click();

    const preview = page.getByTestId("change-preview-change-story-core-1");
    await expect(preview).toContainText("3 个后续版本");
    await expect(preview).toContainText("待重新生成选模方案后计算");
    await expect(page.getByRole("button", { name: "确认创作方案，进入拍摄方案" })).toHaveCount(0);
    expect(state.mediaRequests).toEqual([]);

    await page.getByTestId("confirm-change-change-story-core-1").click();
    await expect(page.getByTestId("director-message")).toContainText("新版本已确认");
    await expect(page.getByTestId("creative-package-review")).toHaveCount(0);
    expect(state.artifacts.story_core.revision_no).toBe(2);
    expect(state.mediaRequests).toEqual([]);

    await page.goto(`/projects/${PROJECT_ID}/production`);
    await expect(page.getByTestId("director-shared-facts")).toContainText("story_core");
    await expect(page.getByTestId("director-shared-facts")).toContainText("第 2 版");
    expect(state.mediaRequests).toEqual([]);
  });
});

test("post-media changes preserve visible batch lineage and require a fresh plan", async ({ page }) => {
  const state = await installDirectorMock(page, (value) => {
    const seeded = baseCreativeArtifacts(value.aspectRatio);
    value.artifacts = {
      story_core: seeded.story_core,
      episode_script: seeded.episode_script,
      story_review: seeded.story_review,
      trial_review: artifact("trial_review", { batch_id: "trial-batch", quality_report_version_id: "trial-quality", decision: "accept", accepted_quality: true, user_note: "试拍通过", evidence_refs: [] }),
    };
    value.status = "awaiting_production_authorization";
    value.batches = [{ ...batch("trial", "trial-batch"), status: "accepted" }];
    value.reservations = [{ id: "trial-reservation", batch_id: "trial-batch", authorization_id: "budget-trial", node_run_id: null, reserved_amount: "1.00", actual_amount: null, currency: "CNY", status: "reserved" }];
  });
  await expectCleanRuntime(page, async () => {
    await page.goto(`/projects/${PROJECT_ID}/quick`);
    await expect(page.getByTestId("post-media-change-notice")).toContainText("1 个静止媒体批次");
    await page.getByTestId("propose-locked-creative-change").click();

    const preview = page.getByTestId("change-preview-change-story-core-1");
    await expect(preview).toContainText("1 个批次将标记为已被修订取代");
    await expect(preview).toContainText("1 笔未结算预留");
    await expect(preview).toContainText("本次故事改动后不自动复用");
    expect(state.mediaRequests).toEqual([]);

    await page.getByTestId("confirm-change-change-story-core-1").click();
    await expect(page.getByTestId("director-message")).toContainText("新版本已确认");
    expect(state.batches[0].status).toBe("superseded_by_change");
    expect(state.reservations[0].status).toBe("released");
    expect(state.mediaRequests).toEqual([]);

    await page.goto(`/projects/${PROJECT_ID}/production`);
    await expect(page.getByTestId("director-batch-trial-batch")).toContainText("trial · superseded_by_change");
    await expect(page.getByTestId("director-reservation-trial-reservation")).toContainText("released · 1.00 CNY");
  });
});

test("formal production, repair, evidence review, and delivery use real gated surfaces", async ({ page }) => {
  const state = await installDirectorMock(page, seedProduction);
  await expectCleanRuntime(page, async () => {
    await page.goto(`/projects/${PROJECT_ID}/quick`);
    await expect(page.getByTestId("production-budget-panel")).toContainText("3.00 CNY");
    await page.getByLabel(/我接受试拍证据/).check();
    await page.getByRole("button", { name: "确认并授权正式生产预算" }).click();
    await expect(page.getByRole("button", { name: "开始正式生产" })).toBeVisible();
    expect(state.mediaRequests).toEqual([]);

    await page.getByRole("button", { name: "开始正式生产" }).click();
    await expect(page.getByRole("button", { name: "运行已结束，生成逐镜质量报告" })).toBeEnabled();
    expect(state.mediaRequests).toEqual([`/api/v1/projects/${PROJECT_ID}/director/production/materialize`]);
    await page.reload();
    await expect(page.getByRole("button", { name: "运行已结束，生成逐镜质量报告" })).toBeEnabled();

    await page.getByRole("button", { name: "运行已结束，生成逐镜质量报告" }).click();
    await expect(page.getByTestId("production-review")).toContainText("人物外观有轻微漂移");
    await page.getByRole("button", { name: "局部修复" }).click();
    await page.getByRole("button", { name: "提交逐镜决定" }).click();
    await expect(page.getByRole("button", { name: "生成三个修复方案" })).toBeVisible();
    await page.getByRole("button", { name: "生成三个修复方案" }).click();
    await expect(page.getByText("强化角色锚点")).toBeVisible();
    expect(state.mediaRequests).toHaveLength(1);

    await page.getByRole("button", { name: "选择这个方案" }).click();
    await expect(page.getByTestId("repair-budget-panel")).toContainText("1.50 CNY");
    await page.getByLabel(/我已看过改动范围/).check();
    await page.getByRole("button", { name: "授权额外预算并开始局部修复" }).click();
    await expect(page.getByRole("button", { name: "运行已结束，生成逐镜质量报告" })).toBeEnabled();
    expect(state.mediaRequests.at(-1)).toContain("/repairs/repair-0123456789ab/authorize");

    await page.getByRole("button", { name: "运行已结束，生成逐镜质量报告" }).click();
    await page.getByRole("button", { name: "接受", exact: true }).click();
    await page.getByLabel("给 AI 导演的验收说明").fill("人物外观的轻微漂移不影响我表达这段故事，我接受当前镜头。");
    await page.getByRole("button", { name: "全部接受并精确导出" }).click();
    await expect(page.getByRole("button", { name: "重试精确导出" })).toBeVisible();
    await page.getByRole("button", { name: "重试精确导出" }).click();
    await expect(page.getByTestId("director-delivery")).toContainText("完整交付");

    await page.reload();
    await expect(page.getByTestId("director-delivery")).toBeVisible();
    await expect(page.getByText("成片 MP4 · 待授权下载")).toBeVisible();
    await page.getByRole("button", { name: "准备四项下载" }).click();
    await expect(page.getByRole("link", { name: "下载成片 MP4" })).toBeVisible();
    await expect(page.getByRole("link", { name: "下载字幕 SRT" })).toBeVisible();
    await expect(page.getByRole("link", { name: "下载时间线 JSON" })).toBeVisible();
    await expect(page.getByRole("link", { name: "下载完整素材包 ZIP" })).toBeVisible();
  });
});

test("project creation sends the selected native 9:16 or 16:9 aspect ratio", async ({ page }) => {
  const state = await installDirectorMock(page);
  await expectCleanRuntime(page, async () => {
    await page.goto("/");
    await expect(page.getByLabel("画幅")).toHaveValue("9:16");
    await expect(page.getByLabel("画幅").locator("option")).toHaveCount(2);
    await page.getByLabel("画幅").selectOption("16:9");
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await expect(page.getByTestId("director-sidebar")).toContainText("16:9");
    expect(state.createdAspects).toEqual(["16:9"]);

    await page.goto("/");
    await expect(page.getByLabel("画幅")).toHaveValue("9:16");
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await expect(page.getByTestId("director-sidebar")).toContainText("9:16");
    expect(state.createdAspects).toEqual(["16:9", "9:16"]);
  });
});
